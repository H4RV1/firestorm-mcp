// SPDX-License-Identifier: MIT
// Bounded observations and guarded plans. Live validation is separate from compilation.
#include "llviewerprecompiledheaders.h"
#include "fsmcpbuilder.h"
#include "fsmcpui.h"
#include "llagent.h"
#include "llviewerregion.h"
#include "llviewercontrol.h"
#include "llworld.h"
#include "rlvactions.h"
#include "fsareasearch.h"
#include "llfloaterreg.h"
#include <chrono>
#include <map>
#include <set>
#include "lleventapi.h"
#include "llsdutil.h"
#include "llsdutil_math.h"
#include "llselectmgr.h"
#include "lltextureentry.h"
#include "llviewerobject.h"
#include "llviewerobjectlist.h"

namespace
{
LLSD describeObject(LLViewerObject* object)
{
    LLSD result = LLSD::emptyMap();
    result["object_id"] = object->getID();
    result["root_id"] = object->getRootEdit()->getID();
    result["region_position"] = ll_sd_from_vector3(object->getPositionRegion());
    result["texture_entry_count"] = (S32)object->getNumTEs();
    result["modify_allowed"] = object->permModify();
    result["copy_allowed"] = object->permCopy();
    result["owned_by_agent"] = object->permYouOwner();
    result["evidence"] = "viewer_object_cache";
    return result;
}

class FSMCPBuilder final : public LLEventAPI
{
public:
    FSMCPBuilder() : LLEventAPI("FSMCPBuilder", "Bounded builder observations and guarded action plans, schema version 1")
    {
        add("getSelection", "Read current selected prims and selected texture-entry indices on [\"reply\"]",
            &FSMCPBuilder::getSelection, LLSD().with("reply", LLSD()));
        add("getLinkset", "Read viewer-cache link order for [\"object_id\"] on [\"reply\"]; completeness is unverified",
            &FSMCPBuilder::getLinkset, LLSD().with("object_id", LLSD()).with("reply", LLSD()));
        add("getFaces", "Read texture entries of [\"object_id\"] on [\"reply\"]; no asset contents or resolved PBR data",
            &FSMCPBuilder::getFaces, LLSD().with("object_id", LLSD()).with("reply", LLSD()));
        add("getNearby", "Bounded loaded prim search: distance<=256, limit<=100, offset into current object cache. Optional owned_only, roots_only and cached_name query.",
            &FSMCPBuilder::getNearby, LLSD().with("reply", LLSD()));
        add("prepareLink", "Prepare a 30-second single-use link/unlink plan for the exact current selection; does not change objects.",
            &FSMCPBuilder::prepareLink, LLSD().with("reply", LLSD()).with("action", LLSD()));
        add("commitLink", "Consume a prepared plan only if agent, region, selection order and root membership remain unchanged. Dispatch evidence only.",
            &FSMCPBuilder::commitLink, LLSD().with("reply", LLSD()).with("plan_id", LLSD()));
        add("selectObjects", "Select 1-32 explicit loaded owned roots after comparing expected_selection. Root order is observable; inspect before prepareLink.",
            &FSMCPBuilder::selectObjects, LLSD().with("reply", LLSD()).with("object_ids", LLSD()).with("expected_selection", LLSD()));
        add("prepareFace", "Prepare a 30-second edit to explicit legacy surface fields: color RGBA, scale, offset, rotation, glow, fullbright. No PBR/asset edits.",
            &FSMCPBuilder::prepareFace, LLSD().with("reply", LLSD()).with("object_id", LLSD()).with("face", LLSD()).with("changes", LLSD()));
        add("commitFace", "Consume a face plan after rechecking session, permissions and unchanged texture entry. Dispatch only; simulator confirmation remains external.",
            &FSMCPBuilder::commitFace, LLSD().with("reply", LLSD()).with("plan_id", LLSD()));
    }

private:
    struct Plan { LLSD selection; LLUUID agent, session, region; std::string action; std::chrono::steady_clock::time_point expires; };
    std::map<LLUUID, Plan> mPlans;
    struct FacePlan { LLUUID object, root, agent, session, region; S32 face; LLSD before, changes; std::chrono::steady_clock::time_point expires; };
    std::map<LLUUID, FacePlan> mFacePlans;

    bool editable(LLViewerObject* object)
    {
        return object && !object->isDead() && object->getVolume() && !object->isAttachment() &&
            object->getRootEdit() && object->getRegion() && object->getRegion() == gAgent.getRegion() &&
            object->permYouOwner() && object->permModify() && !object->isPermanentEnforced() &&
            !object->getRootEdit()->isPermanentEnforced() && RlvActions::canEdit(object);
    }
    void faceChanges(LLTextureEntry& entry, const LLSD& changes)
    {
        if (!changes.isMap() || changes.size() < 1 || changes.size() > 6) throw std::runtime_error("Supply 1-6 supported surface fields");
        for (const auto& pair : llsd::inMap(changes))
        {
            const auto& key = pair.first; const auto& value = pair.second;
            auto number = [](const LLSD& v, F64 low, F64 high) -> F32
            {
                if ((!v.isReal() && !v.isInteger()) || !std::isfinite(v.asReal()) || v.asReal() < low || v.asReal() > high)
                    throw std::runtime_error("Surface parameter out of bounds");
                return (F32)v.asReal();
            };
            if (key == "color")
            {
                if (!value.isArray() || value.size() != 4) throw std::runtime_error("Color requires RGBA");
                entry.setColor(LLColor4(number(value[0], 0, 1), number(value[1], 0, 1), number(value[2], 0, 1), number(value[3], 0, 1)));
            }
            else if (key == "scale" || key == "offset")
            {
                if (!value.isArray() || value.size() != 2) throw std::runtime_error("Scale/offset require two values");
                F32 x = number(value[0], key == "scale" ? -100 : -1, key == "scale" ? 100 : 1);
                F32 y = number(value[1], key == "scale" ? -100 : -1, key == "scale" ? 100 : 1);
                if (key == "scale") entry.setScale(x, y); else entry.setOffset(x, y);
            }
            else if (key == "rotation") entry.setRotation(number(value, -F_TWO_PI, F_TWO_PI));
            else if (key == "glow") entry.setGlow(number(value, 0, 1));
            else if (key == "fullbright")
            { if (!value.isBoolean()) throw std::runtime_error("Fullbright requires boolean"); entry.setFullbright(value.asBoolean()); }
            else throw std::runtime_error("Unsupported surface field; no changes dispatched");
        }
    }
    void prepareFace(const LLSD& r)
    {
        Response response(LLSD(), r);
        auto object = findObject(r);
        S32 face = r["face"].asInteger();
        if (!editable(object) || !r["face"].isInteger() || face < 0 || face >= object->getNumTEs() || !object->getTE(face))
        { response.error("An owned modifiable in-region prim and valid texture-entry index are required"); return; }
        auto now = std::chrono::steady_clock::now();
        for (auto it = mFacePlans.begin(); it != mFacePlans.end();) { if (it->second.expires < now) it = mFacePlans.erase(it); else ++it; }
        if (mFacePlans.size() >= 16) { response.error("Face plan limit reached; wait for expiry"); return; }
        try
        {
            LLTextureEntry edited(*object->getTE(face));
            faceChanges(edited, r["changes"]);
            LLUUID id; id.generate();
            FacePlan plan{object->getID(), object->getRootEdit()->getID(), gAgent.getID(), gAgent.getSessionID(), gAgent.getRegion()->getRegionID(), face,
                object->getTE(face)->asLLSD(), r["changes"], now + std::chrono::seconds(30)};
            mFacePlans.emplace(id, plan);
            response["schema_version"] = 1; response["plan_id"] = id;
            response["before"] = plan.before; response["preview"] = edited.asLLSD();
            response["expires_in_seconds"] = 30; response["world_changed"] = false;
            response["pbr_changed"] = false;
        }
        catch (const std::exception& e) { response.error(e.what()); }
    }
    void commitFace(const LLSD& r)
    {
        Response response(LLSD(), r);
        auto it = mFacePlans.find(r["plan_id"].asUUID());
        if (it == mFacePlans.end()) { response.error("Unknown or consumed face plan; inspect before retrying"); return; }
        FacePlan plan = it->second; mFacePlans.erase(it);
        auto object = gObjectList.findObject(plan.object);
        if (plan.expires < std::chrono::steady_clock::now() || !editable(object) || plan.agent != gAgent.getID() || plan.session != gAgent.getSessionID() ||
            plan.region != gAgent.getRegion()->getRegionID() || plan.root != object->getRootEdit()->getID() ||
            plan.face >= object->getNumTEs() || !object->getTE(plan.face) || !llsd_equals(plan.before, object->getTE(plan.face)->asLLSD()))
        { response.error("Face plan expired or target/session/texture entry changed; nothing dispatched"); return; }
        const LLSD& c = plan.changes;
        if (c.has("color")) object->setTEColor(plan.face, LLColor4((F32)c["color"][0].asReal(), (F32)c["color"][1].asReal(), (F32)c["color"][2].asReal(), (F32)c["color"][3].asReal()));
        if (c.has("scale")) object->setTEScale(plan.face, (F32)c["scale"][0].asReal(), (F32)c["scale"][1].asReal());
        if (c.has("offset")) object->setTEOffset(plan.face, (F32)c["offset"][0].asReal(), (F32)c["offset"][1].asReal());
        if (c.has("rotation")) object->setTERotation(plan.face, (F32)c["rotation"].asReal());
        if (c.has("glow")) object->setTEGlow(plan.face, (F32)c["glow"].asReal());
        if (c.has("fullbright")) object->setTEFullbright(plan.face, c["fullbright"].asBoolean());
        object->sendTEUpdate();
        response["schema_version"] = 1; response["status"] = "dispatched";
        response["verified_effect"] = false; response["object_id"] = plan.object; response["face"] = plan.face;
        response["local_texture_entry"] = object->getTE(plan.face)->asLLSD();
    }

    LLSD selectionIdentity()
    {
        LLSD result = LLSD::emptyArray();
        auto selection = LLSelectMgr::getInstance()->getSelection();
        for (auto iter = selection->begin(); iter != selection->end(); ++iter)
        {
            if (result.size() >= 256) break;
            auto object = (*iter)->getObject();
            if (!object || object->isDead() || !object->getRootEdit()) continue;
            result.append(LLSD().with("object_id", object->getID()).with("root_id", object->getRootEdit()->getID()));
        }
        return result;
    }
    bool validSelection(const std::string& action)
    {
        auto mgr = LLSelectMgr::getInstance();
        auto selection = mgr->getSelection();
        if (!gAgent.getRegion() || selection->getObjectCount() < 1 || selection->getObjectCount() > 256 ||
            !mgr->selectGetAllRootsValid() || !mgr->selectGetSameRegion()) return false;
        for (auto iter = selection->begin(); iter != selection->end(); ++iter)
        {
            auto object = (*iter)->getObject();
            if (!object || object->isDead() || object->isAvatar() || object->isAttachment() ||
                object->getRegion() != gAgent.getRegion() || !object->permYouOwner() || !object->permModify() ||
                object->isPermanentEnforced() || !object->getRootEdit() || object->getRootEdit()->isPermanentEnforced()) return false;
        }
        return action == "link" ? mgr->enableLinkObjects() : action == "unlink" && mgr->enableUnlinkObjects();
    }
    void prepareLink(const LLSD& r)
    {
        Response response(LLSD(), r);
        std::string action = r["action"].asString();
        if (!validSelection(action)) { response.error("Select valid owned modifiable in-region prims; link/unlink is unavailable"); return; }
        auto now = std::chrono::steady_clock::now();
        for (auto it = mPlans.begin(); it != mPlans.end();) { if (it->second.expires < now) it = mPlans.erase(it); else ++it; }
        if (mPlans.size() >= 16) { response.error("Plan limit reached; wait for expiry"); return; }
        LLUUID id; id.generate();
        Plan plan{selectionIdentity(), gAgent.getID(), gAgent.getSessionID(), gAgent.getRegion()->getRegionID(), action, now + std::chrono::seconds(30)};
        mPlans.emplace(id, plan);
        response["schema_version"] = 1; response["plan_id"] = id; response["action"] = action;
        response["selection"] = plan.selection; response["expires_in_seconds"] = 30;
        auto root = LLSelectMgr::getInstance()->getSelection()->getFirstRootObject();
        response["candidate_root_id"] = root ? LLSD(root->getID()) : LLSD();
        response["world_changed"] = false;
    }
    void commitLink(const LLSD& r)
    {
        Response response(LLSD(), r);
        auto it = mPlans.find(r["plan_id"].asUUID());
        if (it == mPlans.end()) { response.error("Unknown or consumed plan; inspect state before creating another"); return; }
        Plan plan = it->second;
        mPlans.erase(it); // Consume BEFORE any dispatch; lost replies never replay.
        if (plan.expires < std::chrono::steady_clock::now() || plan.agent != gAgent.getID() || plan.session != gAgent.getSessionID() || !gAgent.getRegion() ||
            plan.region != gAgent.getRegion()->getRegionID() || !llsd_equals(plan.selection, selectionIdentity()) || !validSelection(plan.action))
        { response.error("Plan expired or session/selection changed; nothing dispatched"); return; }
        auto mgr = LLSelectMgr::getInstance();
        // The normal delayed unlink callback acts on whatever is selected later.
        // Do not queue it: a human selection change would escape this plan guard.
        bool confirmation = plan.action == "unlink" && gSavedSettings.getBOOL("FSUnlinkConfirmEnabled") &&
            mgr->getSelection()->getObjectCount() >= gSavedSettings.getS32("MinObjectsForUnlinkConfirm") &&
            mgr->getSelection()->getObjectCount() > mgr->getSelection()->getRootObjectCount();
        if (!confirmation) { if (plan.action == "link") mgr->linkObjects(); else mgr->unlinkObjects(); }
        response["schema_version"] = 1; response["action"] = plan.action;
        response["status"] = confirmation ? "confirmation_required_no_dispatch" : "dispatched";
        response["verified_effect"] = false;
        response["before_selection"] = plan.selection;
    }
    void selectObjects(const LLSD& r)
    {
        Response response(LLSD(), r);
        if (!r["object_ids"].isArray() || r["object_ids"].size() < 1 || r["object_ids"].size() > 32 ||
            LLSelectMgr::getInstance()->getSelection()->getObjectCount() > 256 ||
            !llsd_equals(r["expected_selection"], selectionIdentity()))
        { response.error("Supply 1-32 root IDs and the exact current selection identity"); return; }
        std::vector<LLViewerObject*> objects;
        std::set<LLUUID> unique;
        for (const LLSD& id : llsd::inArray(r["object_ids"]))
        {
            auto object = gObjectList.findObject(id.asUUID());
            if (!object || object->isDead() || !object->getVolume() || object->isAttachment() ||
                object->getRootEdit() != object || !object->permYouOwner() || !object->permModify() ||
                object->getRegion() != gAgent.getRegion() || !unique.insert(id.asUUID()).second)
            { response.error("Every requested object must be a distinct loaded owned modifiable in-region root"); return; }
            objects.push_back(object);
        }
        auto mgr = LLSelectMgr::getInstance();
        mgr->deselectAll();
        for (auto object : objects) mgr->selectObjectAndFamily(object, true);
        response["schema_version"] = 1; response["selection_identity"] = selectionIdentity();
        response["properties_may_be_pending"] = true; response["selection_input_sent"] = true;
    }
    void getNearby(const LLSD& r)
    {
        Response response(LLSD(), r);
        F64 distance = r.has("distance") ? r["distance"].asReal() : 32;
        S32 limit = r.has("limit") ? r["limit"].asInteger() : 50, offset = r["offset"].asInteger();
        std::string query = r["query"].asString(); LLStringUtil::toLower(query);
        if (!std::isfinite(distance) || distance <= 0 || distance > 256 || limit < 1 || limit > 100 || offset < 0 || query.size() > 128)
        { response.error("Invalid nearby bounds"); return; }
        bool roots = !r.has("roots_only") || r["roots_only"].asBoolean();
        S32 index = offset, count = gObjectList.getNumObjects(), unknown_names = 0;
        auto started = std::chrono::steady_clock::now();
        auto area_search = LLFloaterReg::findTypedInstance<FSAreaSearch>("area_search");
        response["schema_version"] = 1; response["objects"] = LLSD::emptyArray();
        for (; index < count && index - offset < 4096; ++index)
        {
            if (response["objects"].size() >= limit || std::chrono::steady_clock::now() - started > std::chrono::milliseconds(8)) break;
            auto object = gObjectList.getObject(index);
            if (!object || object->isDead() || !object->getVolume() || object->isAttachment() || !object->getRootEdit() ||
                (roots && object->getRootEdit() != object) || (r["owned_only"].asBoolean() && !object->permYouOwner())) continue;
            F64 squared = dist_vec_squared(object->getPositionGlobal(), gAgent.getPositionGlobal());
            if (squared > distance * distance) continue;
            auto node = LLSelectMgr::getInstance()->getSelection()->findNode(object);
            std::string name = node && node->mValid ? node->mName : "";
            std::string source = name.empty() ? "unknown" : "selected_object_properties";
            if (name.empty() && area_search && object->getRegion())
            {
                auto found = area_search->mObjectDetails.find(object->getID());
                if (found != area_search->mObjectDetails.end() && found->second.request == FSObjectProperties::FINISHED &&
                    found->second.region_handle == object->getRegion()->getHandle() && found->second.local_id == object->getLocalID())
                { name = found->second.name; source = "area_search_cache"; }
            }
            std::string lower = name; LLStringUtil::toLower(lower);
            if (name.empty()) ++unknown_names;
            if (!query.empty() && lower.find(query) == std::string::npos) continue;
            LLSD item = describeObject(object);
            item["name"] = name.empty() ? LLSD() : LLSD(name);
            item["name_source"] = source;
            item["distance"] = std::sqrt(squared);
            response["objects"].append(item);
        }
        response["next_offset"] = index < count ? LLSD(index) : LLSD();
        response["unknown_names_in_page"] = unknown_names;
        response["complete_verified"] = false;
        response["name_source"] = "selection_or_existing_area_search_cache";
        response["pagination_consistency"] = "live_object_cache_not_snapshot";
    }
    static LLViewerObject* findObject(const LLSD& request)
    {
        LLViewerObject* object = gObjectList.findObject(request["object_id"].asUUID());
        return object && !object->isDead() && !object->isAvatar() && object->getRootEdit() ? object : nullptr;
    }

    void getSelection(const LLSD& request)
    {
        Response response(LLSD(), request);
        response["schema_version"] = 1;
        response["objects"] = LLSD::emptyArray();
        response["selection_identity"] = selectionIdentity();
        auto selection = LLSelectMgr::getInstance()->getSelection();
        response["truncated"] = selection->getObjectCount() > 256;
        for (auto iter = selection->begin(); iter != selection->end(); ++iter)
        {
            if (response["objects"].size() >= 256) break;
            LLSelectNode* node = *iter;
            LLViewerObject* object = node->getObject();
            if (!object || object->isDead() || object->isAvatar() || !object->getRootEdit()) continue;
            LLSD item = describeObject(object);
            // Object properties may still be arriving. Never invent names.
            item["name"] = node->mValid ? LLSD(node->mName) : LLSD();
            item["properties_received"] = node->mValid;
            item["selected_faces"] = LLSD::emptyArray();
            for (S32 face = 0; face < object->getNumTEs(); ++face)
                if (node->isTESelected(face)) item["selected_faces"].append(face);
            response["objects"].append(item);
        }
    }

    void getLinkset(const LLSD& request)
    {
        Response response(LLSD(), request);
        LLViewerObject* object = findObject(request);
        if (!object) { response.error("Object is not a loaded prim in this viewer"); return; }
        LLViewerObject* root = object->getRootEdit();
        const auto& children = root->getChildren();
        response["schema_version"] = 1;
        response["root_id"] = root->getID();
        response["complete_verified"] = false;
        response["server_link_numbers_verified"] = false;
        response["numbering_source"] = "Firestorm_build_panel_child_order";
        response["prims"] = LLSD::emptyArray();
        LLSD root_data = describeObject(root);
        // Matches llfloatertools.cpp: unlinked root=0, linked root=1.
        root_data["viewer_link_number"] = children.empty() ? 0 : 1;
        response["prims"].append(root_data);
        S32 number = 1;
        for (LLViewerObject* child : children)
        {
            ++number;
            if (!child || child->isDead() || child->isAvatar() || !child->getRootEdit()) continue;
            LLSD data = describeObject(child);
            data["viewer_link_number"] = number;
            response["prims"].append(data);
        }
    }

    void getFaces(const LLSD& request)
    {
        Response response(LLSD(), request);
        LLViewerObject* object = findObject(request);
        if (!object) { response.error("Object is not a loaded prim in this viewer"); return; }
        response["schema_version"] = 1;
        response["object"] = describeObject(object);
        response["faces"] = LLSD::emptyArray();
        response["index_semantics"] = "zero_based_texture_entry";
        response["pbr_assets_resolved"] = false;
        for (S32 index = 0; index < object->getNumTEs(); ++index)
        {
            const LLTextureEntry* entry = object->getTE(index);
            LLSD face = LLSD::emptyMap();
            face["face_index"] = index;
            face["available"] = entry != nullptr;
            if (entry) face["texture_entry"] = entry->asLLSD();
            response["faces"].append(face);
        }
    }
};
}

void initFSMCPBuilder()
{
    static FSMCPBuilder api;
    initFSMCPUI();
}
