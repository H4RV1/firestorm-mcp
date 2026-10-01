// SPDX-License-Identifier: MIT
#include "llviewerprecompiledheaders.h"
#include "fsmcptraining.h"
#include "fsmcptrainingmodel.h"
#include "llagent.h"
#include "llagentcamera.h"
#include "llbutton.h"
#include "llcombobox.h"
#include "lleventapi.h"
#include "llfloaterreg.h"
#include "llgesturemgr.h"
#include "llinventorymodel.h"
#include "llkeyboard.h"
#include "llmultigesture.h"
#include "llrender.h"
#include "llsdutil_math.h"
#include "lltextbox.h"
#include "lltimer.h"
#include "llviewercamera.h"
#include "llviewercontrol.h"
#include "llviewerobjectlist.h"
#include "llviewerregion.h"
#include "llviewershadermgr.h"
#include "llvoavatarself.h"

namespace
{
LLUUID targetID, regionID, agentID;
fsmcp_training::Clock cooldown;
std::string lastAttempt = "No attempt recorded";
LLSD lastSample;
bool wasEnabled = false;
F64 now() { return LLTimer::getTotalSeconds(); }
bool enabled() { return gSavedSettings.getBOOL("FSMCPTrainingEnabled"); }
fsmcp_training::Rules rules()
{
    return { gSavedSettings.getF32("FSMCPTrainingRange"),
        gSavedSettings.getF32("FSMCPTrainingHalfAngle"),
        gSavedSettings.getF32("FSMCPTrainingCooldown"),
        gSavedSettings.getBOOL("FSMCPTrainingEligibleOnly") };
}
void reset()
{
    targetID.setNull(); cooldown.reset(); lastAttempt = "No attempt recorded"; lastSample = LLSD();
}
bool context()
{
    const bool on = enabled();
    const bool valid = isAgentAvatarValid() && gAgent.getRegion() && !gAgentAvatarp->isDead();
    const LLUUID region = valid ? gAgent.getRegion()->getRegionID() : LLUUID::null;
    if (!on || !valid || region != regionID || agentID != gAgent.getID() || on != wasEnabled) reset();
    regionID = region; agentID = gAgent.getID(); wasEnabled = on;
    return on && valid && rules().valid();
}
LLVOAvatar* target()
{
    LLViewerObject* object = gObjectList.findObject(targetID);
    if (!object || object->isDead() || !object->isAvatar() || object->getRegion() != gAgent.getRegion()) return nullptr;
    auto* avatar = static_cast<LLVOAvatar*>(object);
    return avatar->isSelf() || avatar->isControlAvatar() ? nullptr : avatar;
}
LLVector3 forward()
{
    LLVector3 value = gAgentCamera.cameraMouselook() ? LLViewerCamera::getInstance()->getAtAxis() : gAgent.getAtAxis();
    value.normalize(); return value;
}
fsmcp_training::Geometry geometry()
{
    auto* avatar = target();
    if (!avatar || !isAgentAvatarValid()) return {};
    LLVector3 delta = avatar->getPositionAgent() - gAgentAvatarp->getPositionAgent();
    LLVector3 facing = forward();
    return fsmcp_training::evaluate({delta.mV[0],delta.mV[1],delta.mV[2]},
        {facing.mV[0],facing.mV[1],facing.mV[2]},rules());
}
bool acquireNearest()
{
    if (!context()) return false;
    LLVOAvatar* nearest = nullptr;
    F64 best = std::numeric_limits<F64>::infinity();
    for (LLCharacter* character : LLCharacter::sInstances)
    {
        auto* avatar = dynamic_cast<LLVOAvatar*>(character);
        if (!avatar || avatar->isDead() || avatar->isSelf() || avatar->isControlAvatar() ||
            avatar->getRegion() != gAgent.getRegion()) continue;
        F64 distance = (avatar->getPositionAgent() - gAgentAvatarp->getPositionAgent()).lengthSquared();
        if (std::isfinite(distance) && (distance < best ||
            (distance == best && nearest && avatar->getID() < nearest->getID())))
        { best = distance; nearest = avatar; }
    }
    targetID = nearest ? nearest->getID() : LLUUID::null;
    // Target switching never resets cooldown.
    return nearest != nullptr;
}
void recordAttempt()
{
    if (!context()) return;
    const auto sample = geometry();
    const F64 time = now();
    lastSample["target_id"] = targetID;
    lastSample["local_time_seconds"] = time;
    lastSample["distance_m"] = sample.known ? LLSD(sample.distance) : LLSD();
    lastSample["angle_degrees"] = sample.known ? LLSD(sample.angle_degrees) : LLSD();
    lastSample["cooldown_before_seconds"] = cooldown.remaining(time);
    lastSample["range_m"] = rules().range;
    lastSample["half_angle_degrees"] = rules().half_angle_degrees;
    switch (cooldown.attempt(time, sample, rules()))
    {
    case fsmcp_training::Attempt::eligible: lastAttempt = "Predicted eligible (not a confirmed hit)"; break;
    case fsmcp_training::Attempt::cooling_down: lastAttempt = "Too early - cooldown unchanged"; break;
    case fsmcp_training::Attempt::outside_volume: lastAttempt = "Outside configured range or angle"; break;
    default: lastAttempt = "Unknown - target/geometry unavailable"; break;
    }
    lastSample["result"] = lastAttempt;
}
LLSD state()
{
    const bool active = context();
    const auto r = rules();
    const auto g = active ? geometry() : fsmcp_training::Geometry();
    LLSD value;
    value["schema_version"] = 1;
    value["enabled"] = enabled(); value["available"] = active;
    value["evidence"] = "local_viewer_prediction";
    value["simulator_hit_verified"] = false;
    value["target_selection_verified"] = false;
    value["target_id"] = targetID;
    value["target_loaded"] = active && target() != nullptr;
    value["sample_local_time_seconds"] = now();
    value["simulator_sample_age_seconds"] = LLSD();
    value["last_attempt_sample"] = lastSample;
    if (active)
    {
        value["self_position_agent"] = ll_sd_from_vector3(gAgentAvatarp->getPositionAgent());
        value["self_velocity_mps"] = ll_sd_from_vector3(gAgentAvatarp->getVelocity());
        value["forward"] = ll_sd_from_vector3(forward());
        if (auto* avatar = target())
        {
            value["target_position_agent"] = ll_sd_from_vector3(avatar->getPositionAgent());
            value["target_velocity_mps"] = ll_sd_from_vector3(avatar->getVelocity());
        }
    }
    value["range_m"] = r.range; value["half_angle_degrees"] = r.half_angle_degrees;
    value["cooldown_seconds"] = r.cooldown;
    value["cooldown_remaining_seconds"] = cooldown.remaining(now());
    value["cooldown_mode"] = r.eligible_only ? "predicted_eligible_attempt" : "every_ready_attempt";
    value["distance_m"] = g.known ? LLSD(g.distance) : LLSD();
    value["range_margin_m"] = g.known ? LLSD(r.range - g.distance) : LLSD();
    value["angle_degrees"] = g.known ? LLSD(g.angle_degrees) : LLSD();
    value["in_range"] = g.known ? LLSD(g.in_range) : LLSD();
    value["in_front"] = g.known ? LLSD(g.in_front) : LLSD();
    value["predicted_eligible"] = g.known ? LLSD(g.eligible() && cooldown.remaining(now()) <= 0) : LLSD();
    value["last_attempt"] = lastAttempt;
    return value;
}
class TrainingAPI final : public LLEventAPI
{
public:
    TrainingAPI() : LLEventAPI("FSMCPTraining", "Local range and timing rehearsal; never sends attacks or confirms simulator hits")
    {
        add("getState", "Read local prediction and nullable geometry on reply", &TrainingAPI::getState, LLSD().with("reply",LLSD()));
        add("acquireNearest", "Lock nearest loaded same-region avatar locally; does not target the combat system", &TrainingAPI::acquire, LLSD().with("reply",LLSD()));
        add("recordAttempt", "Rehearse timing locally; does not trigger a gesture, damage or chat", &TrainingAPI::attempt, LLSD().with("reply",LLSD()));
    }
private:
    void getState(const LLSD& request) { Response response(state(),request); }
    void acquire(const LLSD& request) { acquireNearest(); Response response(state(),request); }
    void attempt(const LLSD& request) { recordAttempt(); Response response(state(),request); }
};
}

void initFSMCPTraining()
{
    static TrainingAPI api;
    LLFloaterReg::add("fsmcp_training", "floater_fsmcp_training.xml", &LLFloaterReg::build<FSMCPTrainingFloater>);
}
bool FSMCPTrainingFloater::postBuild()
{
    getChild<LLButton>("nearest")->setCommitCallback([](LLUICtrl*,const LLSD&){ acquireNearest(); });
    getChild<LLButton>("attempt")->setCommitCallback([](LLUICtrl*,const LLSD&){ recordAttempt(); });
    getChild<LLButton>("refresh")->setCommitCallback([this](LLUICtrl*,const LLSD&){ refreshGestures(); });
    for (const auto& item : {std::make_pair("target_gesture","FSMCPTrainingTargetGesture"),std::make_pair("attack_gesture","FSMCPTrainingAttackGesture")})
    {
        const std::string setting = item.second;
        getChild<LLComboBox>(item.first)->setCommitCallback([setting](LLUICtrl* control,const LLSD&){gSavedSettings.setString(setting,control->getValue().asString());});
    }
    return true;
}
void FSMCPTrainingFloater::onOpen(const LLSD&) { refreshGestures(); }
void FSMCPTrainingFloater::refreshGestures()
{
    for (const auto& item : {std::make_pair("target_gesture","FSMCPTrainingTargetGesture"),std::make_pair("attack_gesture","FSMCPTrainingAttackGesture")})
    {
        auto* combo = getChild<LLComboBox>(item.first);
        combo->removeall(); combo->add("None - manual rehearsal", LLSD(""));
        const std::string selected = gSavedSettings.getString(item.second);
        bool found = selected.empty();
        for (const auto& entry : LLGestureMgr::instance().getActiveGestures())
        {
            if (!entry.second) continue;
            auto* inventory = gInventory.getItem(entry.first);
            std::string label = inventory ? inventory->getName() : entry.first.asString();
            label += " [" + LLKeyboard::stringFromAccelerator(entry.second->mMask,entry.second->mKey) + "]";
            combo->add(label, LLSD(entry.first.asString()));
            found = found || entry.first.asString() == selected;
        }
        if (!found) combo->add("Previously bound gesture (inactive)", LLSD(selected));
        combo->setValue(selected);
    }
}
void FSMCPTrainingFloater::draw()
{
    LLSD value = state();
    std::string summary;
    if (!value["available"].asBoolean()) summary = "Overlay off, invalid settings, or avatar unavailable";
    else if (!value["target_loaded"].asBoolean()) summary = "No loaded target - select nearest or use your bound gesture";
    else if (value["distance_m"].isUndefined()) summary = "Target geometry unknown";
    else summary = llformat("Distance %.2f m | Angle %.1f deg | %s | %s",
        value["distance_m"].asReal(),value["angle_degrees"].asReal(),
        value["in_range"].asBoolean()?"IN RANGE":"OUT OF RANGE",value["in_front"].asBoolean()?"IN FRONT":"OUTSIDE ARC");
    getChild<LLTextBox>("geometry")->setText(summary);
    getChild<LLTextBox>("timing")->setText(llformat("Local cooldown: %.2f s | %s",value["cooldown_remaining_seconds"].asReal(),value["predicted_eligible"].asBoolean()?"READY + IN VOLUME":"NOT ELIGIBLE"));
    getChild<LLTextBox>("last_attempt")->setText(lastAttempt);
    const bool active = value["available"].asBoolean();
    getChild<LLButton>("nearest")->setEnabled(active); getChild<LLButton>("attempt")->setEnabled(active);
    LLFloater::draw();
}
void observeFSMCPTrainingGesture(const LLMultiGesture* gesture)
{
    if (!context()) return;
    const std::string targeting = gSavedSettings.getString("FSMCPTrainingTargetGesture");
    const std::string attacking = gSavedSettings.getString("FSMCPTrainingAttackGesture");
    auto matchesShortcut = [&](const char* setting) {
        const std::string shortcut = gSavedSettings.getString(setting);
        KEY key = KEY_NONE;
        return !shortcut.empty() && LLKeyboard::keyFromString(shortcut,&key) &&
            gesture->mKey == key && gesture->mMask == MASK_NONE;
    };
    for (const auto& entry : LLGestureMgr::instance().getActiveGestures())
    {
        if (entry.second != gesture) continue;
        const bool select = targeting.empty() ? matchesShortcut("FSMCPTrainingTargetShortcut") : entry.first.asString() == targeting;
        const bool attack = attacking.empty() ? matchesShortcut("FSMCPTrainingAttackShortcut") : entry.first.asString() == attacking;
        if (select && attack) { lastAttempt="Bind two different gestures"; return; }
        if (select) acquireNearest();
        if (attack) recordAttempt();
        return;
    }
}
void renderFSMCPTraining()
{
    if (!context()) return;
    const auto r = rules();
    const auto g = geometry();
    const LLVector3 origin = gAgentAvatarp->getPositionAgent();
    const LLVector3 facing = forward();
    LLVector3 side = facing % LLVector3::z_axis;
    if (side.lengthSquared() < .001f) side = facing % LLVector3::y_axis;
    side.normalize(); LLVector3 up = side % facing; up.normalize();
    gGL.flush(); gDebugProgram.bind();
    gGL.getTexUnit(0)->unbind(LLTexUnit::TT_TEXTURE);
    LLGLDepthTest depth(GL_TRUE,GL_FALSE);
    LLGLEnable blend(GL_BLEND);
    gGL.setSceneBlendType(LLRender::BT_ALPHA);
    const bool ready = cooldown.remaining(now()) <= 0;
    if (!g.known) gGL.color4f(.65f,.65f,.65f,.85f);
    else if (!ready) gGL.color4f(1.f,.7f,.1f,.85f);
    else if (g.eligible()) gGL.color4f(.1f,1.f,.3f,.85f);
    else gGL.color4f(1.f,.25f,.2f,.85f);
    auto point = [&](F64 theta,F64 phi) {
        return origin + (F32)r.range * ((F32)std::cos(theta)*facing +
            (F32)(std::sin(theta)*std::cos(phi))*side + (F32)(std::sin(theta)*std::sin(phi))*up);
    };
    auto line = [](const LLVector3& a,const LLVector3& b) {gGL.vertex3fv(a.mV);gGL.vertex3fv(b.mV);};
    const F64 arc = r.half_angle_degrees * fsmcp_training::pi / 180.;
    gGL.begin(LLRender::LINES);
    for (int j=0;j<8;++j)
    {
        F64 phi=F_TWO_PI*j/8.;
        if (r.half_angle_degrees < 180) line(origin,point(arc,phi));
        for(int i=0;i<24;++i) line(point(arc*i/24.,phi),point(arc*(i+1)/24.,phi));
    }
    for(int i=0;i<64;++i) line(point(arc,F_TWO_PI*i/64.),point(arc,F_TWO_PI*(i+1)/64.));
    if(auto* avatar=target())
    {
        const LLVector3 p=avatar->getPositionAgent();
        line(origin,p);
        for(const auto& axis : {LLVector3::x_axis,LLVector3::y_axis,LLVector3::z_axis}) line(p-.12f*axis,p+.12f*axis);
    }
    line(origin,origin + .35f*facing);
    gGL.end(); gGL.flush(); gDebugProgram.unbind();
}
