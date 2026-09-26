// SPDX-License-Identifier: MIT
// FSMCPAssets v1. Viewer objects stay on the main thread. HTTP coroutines yield;
// codec work owns only immutable bytes on a worker. No login/capability export.
#include "llviewerprecompiledheaders.h"
#include "fsmcpassets.h"
#include "fsmcpassetpolicy.h"
#include "fsmcpsound.h"
#include "llagent.h"
#include "llagentui.h"
#include "llagentbenefits.h"
#include "llappviewer.h"
#include "llstartup.h"
#include "llviewernetwork.h"
#include "llviewerregion.h"
#include "llinventorymodel.h"
#include "llinventorydefines.h"
#include "llviewerinventory.h"
#include "llviewerassetupload.h"
#include "llviewerobject.h"
#include "llviewerobjectlist.h"
#include "llviewerwindow.h"
#include "lltoolgrab.h"
#include "llselectmgr.h"
#include "llnotecard.h"
#include "message.h"
#include "lleventapi.h"
#include "lleventcoro.h"
#include "llcoros.h"
#include "llcorehttputil.h"
#include "llsdserialize.h"
#include "llsdutil.h"
#include "llsdutil_math.h"
#include "llframetimer.h"
#include "llchat.h"
#include "httpoptions.h"
#include "bufferarray.h"
#include <vorbis/vorbisfile.h>
#include <future>
#include <deque>
#include <set>
#include <sstream>

namespace {
constexpr size_t MAX_AUDIO = 8 * 1024 * 1024;
constexpr size_t CHUNK = 48 * 1024;
constexpr size_t MAX_JOBS = 128;
constexpr size_t MAX_ROWS = 10000;
const char* CAPS[] = {"FetchInventoryDescendents2", "CreateInventoryCategory", "NewFileAgentInventory",
    "UpdateNotecardAgentInventory", "RequestTaskInventory"};
double now() { return LLFrameTimer::getTotalSeconds(); }
struct Failure : std::runtime_error {
    std::string code;
    Failure(const std::string& c, const std::string& message): std::runtime_error(message), code(c) {}
};
void require(bool condition, const char* code, const char* message) { if (!condition) throw Failure(code, message); }
LLUUID uuid(const LLSD& value) {
    LLUUID id(value.asString());
    require(id.notNull(), "invalid_request", "A nonzero UUID is required."); return id;
}
bool terminal(const std::string& s) { return s == "succeeded" || s == "failed" || s == "cancelled" || s == "unknown"; }
LLSD error(const std::string& code, const std::string& message, bool unknown = false) {
    return LLSD().with("code", code).with("message", message).with("unknownOutcome", unknown);
}
void boundedText(const LLSD& value, size_t maximum, bool multiline = false) {
    std::string s = value.asString();
    require(value.isString() && s.size() <= maximum && (multiline || !s.empty()), "invalid_request", "Invalid text length.");
    require(utf8str_to_utf16str(s).empty() == s.empty() && utf16str_to_utf8str(utf8str_to_utf16str(s)) == s,
        "invalid_request", "Text must be valid UTF-8.");
    for (unsigned char c : s) require(c != 0 && (multiline || (c >= 32 && c != '|')), "invalid_request", "Invalid text character.");
    if (!multiline) require(s.front() != ' ' && s.back() != ' ', "invalid_request", "Text must not have surrounding spaces.");
}

struct Job {
    std::string id, request, fingerprint, kind, lease, bytes;
    LLSD args, expected, result, failure, acknowledged;
    std::string state = "queued", phase = "queued";
    bool submitted = false, cancelled = false;
    double created = now(), deadline = now() + 180;
};
struct Stage { std::string bytes, lease; double expires = now() + 120; };
struct Watch { LLUUID object; std::string lease, generation; double expires; int cursor = 0; std::deque<LLSD> events; };


LLSD itemRow(LLInventoryItem* item) {
    const auto& p = item->getPermissions();
    return LLSD().with("id", item->getUUID()).with("parentId", item->getParentUUID())
        .with("assetId", item->getAssetUUID()).with("name", item->getName()).with("description", item->getDescription())
        .with("assetType", LLAssetType::lookup(item->getType())).with("inventoryType", LLInventoryType::lookup(item->getInventoryType()))
        .with("ownerId", p.getOwner()).with("groupOwned", p.isGroupOwned())
        .with("canCopy", p.allowCopyBy(gAgent.getID())).with("canModify", p.allowModifyBy(gAgent.getID()))
        .with("canTransfer", p.allowTransferTo(LLUUID::null));
}

LLSD cachedPath(LLUUID id) {
    std::vector<LLSD> ancestors; std::set<LLUUID> seen; bool complete = false;
    for (int depth = 0; depth < 256 && seen.insert(id).second; ++depth) {
        auto* cat = gInventory.getCategory(id); if (!cat || cat->getOwnerID() != gAgent.getID()) break;
        ancestors.push_back(LLSD().with("id", id).with("parentId", cat->getParentUUID()).with("name", cat->getName()));
        if (id == gInventory.getRootFolderID()) { complete = true; break; }
        id = cat->getParentUUID();
    }
    LLSD crumbs = LLSD::emptyArray(); std::string path;
    if (complete) for (auto i = ancestors.rbegin(); i != ancestors.rend(); ++i) {
        crumbs.append(*i); if (!path.empty()) path += " / "; path += (*i)["name"].asString();
    }
    return LLSD().with("path", path).with("breadcrumbs", crumbs).with("pathFreshness", "viewer_cache").with("pathComplete", complete);
}

class Assets final : public LLEventAPI {
public:
    Assets(): LLEventAPI("FSMCPAssets", "Generic asset/inventory jobs; contract version 1") {
        add("status", "Session readiness, generation, capabilities and limits on [\"reply\"]", &Assets::status);
        add("lease", "Internal bridge lease synchronization; not a consumer operation", &Assets::lease);
        add("stage", "Append <=49152 binary bytes to one bounded sound stage", &Assets::stage);
        add("discard", "Discard a stage owned by the current lease", &Assets::discard);
        add("submit", "Submit version 1 job with requestId, fingerprint, expected and arguments", &Assets::submit);
        add("job", "Read retained job state by jobId", &Assets::job);
        add("cancel", "Stop before the next irreversible stage; sent work is not retracted", &Assets::cancel);
        add("watch", "Create bounded subscription to one owned in-region object", &Assets::watch);
        add("events", "Read only the selected object's retained dialog/owner-chat events", &Assets::events);
        add("unwatch", "End one object subscription", &Assets::unwatch);
        LLEventPumps::instance().obtain("mainloop").listen("FSMCPAssets-generation", [this](const LLSD&) { observe(); return false; });
    }
    void properties(LLMessageSystem* msg);
    void chat(LLMessageSystem* msg);
    void dialog(LLMessageSystem* msg);
    void loginBenefits(const LLUUID& avatar, const LLSD& cost) {
        mBenefitAvatar = avatar; mBenefitGrid = LLGridManager::instance().getGrid();
        mVerifiedFee = cost.isInteger() && cost.asInteger() >= 0 ? cost.asInteger() : -1;
    }
    void answered(const LLUUID& object, int channel) {
        for (auto& w : mWatches) for (auto& e : w.second.events)
            if (e["type"].asString() == "dialog" && e["objectId"].asUUID() == object && e["channel"].asInteger() == channel) e["responded"] = true;
    }
private:
    std::string mGeneration = LLUUID::generateNewID().asString(), mLease;
    double mLeaseUntil = 0;
    LLSD mIdentity;
    LLUUID mBenefitAvatar;
    std::string mBenefitGrid;
    int mVerifiedFee = -1;
    std::map<std::string, std::shared_ptr<Job>> mJobs;
    std::map<std::string, Stage> mStages;
    std::map<std::string, Watch> mWatches;
    std::map<LLUUID, LLSD> mProperties;
    bool mActive = false;
    std::deque<std::shared_ptr<Job>> mQueue;
    int soundCost() const {
        int cost = LLAgentBenefitsMgr::current().getSoundUploadCost();
        return mBenefitAvatar == gAgent.getID() && mBenefitGrid == LLGridManager::instance().getGrid() &&
            mVerifiedFee >= 0 && cost == mVerifiedFee ? cost : -1;
    }
    std::string grid() const {
        auto& gm = LLGridManager::instance();
        if (gm.isInSLMain()) return "agni";
        if (gm.isInSLBeta()) return "aditi";
        return gm.getGrid().empty() ? "unknown" : "opensim";
    }
    bool ready() const { return LLStartUp::getStartupState() == STATE_STARTED && !gDisconnected &&
        !LLAppViewer::instance()->logoutRequestSent() && gAgent.getID().notNull() && gAgent.getRegion() &&
        gAgent.getRegion()->capabilitiesReceived() && gInventory.getRootFolderID().notNull(); }
    void observe() {
        LLSD identity; identity["ready"] = ready(); identity["agent"] = gAgent.getID();
        identity["session"] = gAgent.getSessionID(); // compared only; never included in responses
        identity["grid"] = LLGridManager::instance().getGrid();
        if (auto* region = gAgent.getRegion()) {
            identity["region"] = region->getRegionID();
            for (auto cap : CAPS) identity[cap] = region->getCapability(cap);
        }
        if (identity != mIdentity) { mIdentity = identity; mGeneration = LLUUID::generateNewID().asString(); mWatches.clear(); mProperties.clear(); }
        for (auto i = mStages.begin(); i != mStages.end();) {
            if (now() > i->second.expires) i = mStages.erase(i); else ++i;
        }
        for (auto i = mWatches.begin(); i != mWatches.end();) {
            if (now() > i->second.expires || now() > mLeaseUntil || i->second.lease != mLease) i = mWatches.erase(i); else ++i;
        }
    }
    void check(const Job& j, bool write = false) {
        observe();
        require(ready(), "not_ready", "Viewer login, region capabilities and inventory must be ready.");
        require(fsmcp::sameSession(ready(), gAgent.getID().asString(), grid(), mGeneration,
            j.expected["avatarId"].asUUID().asString(), j.expected["grid"].asString(), j.expected["generation"].asString()),
            "session_changed", "Viewer session, grid, region or capabilities changed; inspect before continuing.");
        require(now() < j.deadline, "job_timeout", "Job deadline exceeded; reconcile before retrying.");
        if (write) {
            require(!j.cancelled, "cancelled", "Stopped before the next submission.");
            require(now() < mLeaseUntil && !mLease.empty() && j.lease == mLease, "lease_expired", "An active controlling lease is required before submission.");
        }
    }
    void activeLease(const LLSD& r) { require(!mLease.empty() && r["leaseId"].asString() == mLease && now() < mLeaseUntil,
        "lease_required", "Acquire a bounded control lease."); }
    void result(const LLSD& r, const LLSD& value) { Response response(value, r); response["schema_version"] = 1; }
    template <typename F> void safe(const LLSD& r, F fn) {
        try { result(r, fn()); } catch (const Failure& e) { result(r, LLSD().with("ok", false).with("failure", error(e.code, e.what()))); }
        catch (...) { result(r, LLSD().with("ok", false).with("failure", error("internal_error", "Asset operation could not complete."))); }
    }
    void status(const LLSD& r) { safe(r, [&] {
        observe(); LLSD s; s["ok"] = true; s["contractVersion"] = 1; s["connected"] = ready(); s["regionReady"] = ready();
        s["avatarId"] = gAgent.getID(); std::string name; LLAgentUI::buildFullname(name); s["avatarName"] = name;
        s["rootFolderId"] = gInventory.getRootFolderID(); s["grid"] = grid(); s["generation"] = mGeneration;
        int fee = soundCost();
        s["soundUploadCost"] = ready() && (grid() == "agni" || grid() == "aditi") && fee >= 0 ? LLSD(fee) : LLSD();
        s["limits"] = LLSD().with("audioBytes", (int)MAX_AUDIO).with("chunkBytes", (int)CHUNK).with("notecardBytes", 65536)
            .with("retainedJobs", (int)MAX_JOBS).with("concurrency", 1).with("queuedJobs", 8).with("stages", 4)
            .with("eventsPerWatch", 64).with("watches", 8).with("inventoryRows", (int)MAX_ROWS).with("jobResultBytes", 2 * 1024 * 1024);
        LLSD supported;
        for (auto cap : CAPS) supported[cap] = ready() && !gAgent.getRegion()->getCapability(cap).empty();
        s["capabilities"] = supported; s["operations"] = LLSD::emptyArray();
        for (auto op : {"listInventory","searchFolders","createFolder","trashEmptyFolder","uploadSound","createNotecard",
                        "objectInfo","taskInventory","deliverItem","touch","dialogReply","reconcile"}) s["operations"].append(op);
        return s;
    }); }
    void lease(const LLSD& r) { safe(r, [&] {
        mLease = r["leaseId"].asString(); mLeaseUntil = now() + llclamp(r["seconds"].asReal(), 0., 1800.);
        observe(); return LLSD().with("ok", true);
    }); }
    void stage(const LLSD& r) { safe(r, [&] {
        observe(); activeLease(r); std::string id = uuid(r["stageId"]).asString();
        auto data = r["data"].asBinary();
        require(r["data"].isBinary() && data.size() <= CHUNK && r["offset"].isInteger(), "invalid_request", "Invalid staging chunk.");
        auto it = mStages.find(id);
        if (it == mStages.end()) {
            require(mStages.size() < 4 && r["offset"].asInteger() == 0, "stage_limit", "Stage capacity or offset is invalid.");
            it = mStages.emplace(id, Stage{}).first; it->second.lease = mLease;
        }
        auto& st = it->second;
        require(st.lease == mLease, "lease_required", "Stage belongs to another lease.");
        require(r["offset"].asInteger() >= 0 && (size_t)r["offset"].asInteger() == st.bytes.size(), "stage_offset", "Stage offset mismatch; discard and restage.");
        require(st.bytes.size() + data.size() <= MAX_AUDIO, "payload_too_large", "Audio exceeds 8 MiB.");
        st.bytes.append((const char*)data.data(), data.size()); st.expires = now() + 120;
        return LLSD().with("ok", true).with("offset", (int)st.bytes.size());
    }); }
    void discard(const LLSD& r) { safe(r, [&] { activeLease(r); auto it = mStages.find(r["stageId"].asString());
        if (it != mStages.end()) { require(it->second.lease == mLease, "lease_required", "Stage belongs to another lease."); mStages.erase(it); }
        return LLSD().with("ok", true); }); }
    LLSD describe(const Job& j) {
        return LLSD().with("ok", true).with("jobId", j.id).with("requestId", j.request).with("fingerprint", j.fingerprint).with("state", j.state)
            .with("phase", j.phase).with("submitted", j.submitted).with("cancelRequested", j.cancelled)
            .with("unknownOutcome", j.state == "unknown").with("result", j.result).with("failure", j.failure).with("acknowledged", j.acknowledged);
    }
    void submit(const LLSD& r) { safe(r, [&] {
        activeLease(r); std::string req = uuid(r["requestId"]).asString(), fp = r["fingerprint"].asString();
        require(fp.size() == 64 && r["arguments"].isMap(), "invalid_request", "Invalid job fingerprint or arguments.");
        std::ostringstream metadata; LLSDSerialize::toNotation(r["arguments"], metadata);
        require(metadata.str().size() <= 128 * 1024, "payload_too_large", "Job metadata exceeds 128 KiB.");
        for (const auto& entry : mJobs) if (entry.second->request == req) {
            require(entry.second->fingerprint == fp, "request_conflict", "Request ID has different arguments."); return describe(*entry.second);
        }
        require(mQueue.size() < 8, "busy", "Job queue is full.");
        if (mJobs.size() >= MAX_JOBS) {
            auto oldest = mJobs.end();
            for (auto i = mJobs.begin(); i != mJobs.end(); ++i) if (terminal(i->second->state) &&
                (oldest == mJobs.end() || i->second->created < oldest->second->created)) oldest = i;
            require(oldest != mJobs.end(), "busy", "Retained job capacity reached."); mJobs.erase(oldest);
        }
        auto j = std::make_shared<Job>(); j->id = LLUUID::generateNewID().asString(); j->request = req; j->fingerprint = fp;
        j->args = r["arguments"]; j->kind = r["kind"].asString(); j->expected = r["expected"]; j->lease = mLease;
        check(*j, true);
        if (j->kind == "uploadSound") {
            auto stage = mStages.find(j->args["stageId"].asString());
            require(stage != mStages.end() && stage->second.lease == mLease && now() < stage->second.expires,
                "stage_missing", "A complete sound stage is required.");
            j->bytes = std::move(stage->second.bytes); mStages.erase(stage);
        }
        mJobs.emplace(j->id, j); mQueue.push_back(j);
        if (!mActive) { mActive = true; LLCoros::instance().launch("FSMCPAssets-jobs", [this] { drain(); }); }
        return describe(*j);
    }); }
    void job(const LLSD& r) { safe(r, [&] { auto i = mJobs.find(r["jobId"].asString());
        if (i == mJobs.end() && r.has("requestId")) for (auto it = mJobs.begin(); it != mJobs.end(); ++it)
            if (it->second->request == r["requestId"].asString()) { i = it; break; }
        require(i != mJobs.end(), "job_missing", "Job not retained; use durable reconciliation."); return describe(*i->second); }); }
    void cancel(const LLSD& r) { safe(r, [&] { activeLease(r); auto i = mJobs.find(r["jobId"].asString());
        require(i != mJobs.end(), "job_missing", "Job not retained.");
        require(i->second->lease == mLease, "lease_required", "Job belongs to another lease."); i->second->cancelled = true; return describe(*i->second); }); }
    void drain() {
        llcoro::suspendUntilNextFrame(); // return submit acknowledgement before work begins
        while (!mQueue.empty()) {
            auto j = mQueue.front(); mQueue.pop_front();
            try { check(*j, true); j->state = "running"; j->phase = "preflight"; LLSD value = execute(*j); check(*j);
                std::ostringstream encoded; LLSDSerialize::toNotation(value, encoded);
                require(encoded.str().size() <= 2 * 1024 * 1024, "result_limit", "Result exceeds the 2 MiB retained-job limit; narrow the query.");
                j->result = value;
                j->state = "succeeded"; j->phase = "complete";
            } catch (const Failure& e) {
                j->state = fsmcp::interruptedState(j->submitted, e.code == "cancelled");
                j->failure = error(e.code, e.what(), j->submitted);
                j->failure["jobId"] = j->id;
                if (j->acknowledged.has("folderId")) j->failure["acknowledgedFolderId"] = j->acknowledged["folderId"];
                if (j->acknowledged.has("itemId")) j->failure["acknowledgedItemId"] = j->acknowledged["itemId"];
            } catch (...) { j->state = j->submitted ? "unknown" : "failed"; j->failure = error("internal_error", "Job could not complete; inspect saved identifiers.", j->submitted); }
            std::string().swap(j->bytes);
            llcoro::suspendUntilNextFrame();
        }
        mActive = false;
    }
    std::string cap(Job& j, const char* name) { check(j); auto url = gAgent.getRegion()->getCapability(name);
        require(url.substr(0, 8) == "https://", "capability_unavailable", "Required HTTPS region capability is unavailable."); return url; }
    LLSD http(Job& j, const std::string& url, const LLSD& body, bool get = false, const std::string* bytes = nullptr) {
        check(j); require(url.substr(0, 8) == "https://", "invalid_capability", "Upload endpoint must use HTTPS.");
        auto opts = std::make_shared<LLCore::HttpOptions>(); opts->setTimeout(45); opts->setTransferTimeout(45);
        opts->setRetries(0); opts->setFollowRedirects(false); opts->setSSLVerifyPeer(true); opts->setSSLVerifyHost(true);
        auto req = std::make_shared<LLCore::HttpRequest>();
        LLCoreHttpUtil::HttpCoroutineAdapter adapter("FSMCPAssets", LLCore::HttpRequest::DEFAULT_POLICY_ID);
        LLSD response;
        if (bytes) {
            LLCore::BufferArray::ptr_t buffer(new LLCore::BufferArray());
            // Bound per-frame copy work for the largest permitted payload.
            for (size_t offset = 0; offset < bytes->size(); offset += 512 * 1024) {
                buffer->append(bytes->data() + offset, llmin(size_t(512 * 1024), bytes->size() - offset));
                llcoro::suspendUntilNextFrame(); check(j, true);
            }
            auto headers = std::make_shared<LLCore::HttpHeaders>(); headers->append("Content-Type", "application/octet-stream");
            check(j, true);
            if (j.kind == "uploadSound") require(soundCost() == 0,
                "cost_not_zero", "Account benefits changed before sending sound bytes.");
            j.submitted = true; j.phase = "submitted";
            response = adapter.postAndSuspend(req, url, buffer, opts, headers);
        } else if (get) response = adapter.getAndSuspend(req, url, opts);
        else response = adapter.postAndSuspend(req, url, body, opts);
        // Preserve acknowledged IDs even if the session changes while awaiting the reply.
        if (j.submitted) {
            if (j.kind == "createFolder" && response["folder_id"].asUUID().notNull()) j.acknowledged["folderId"] = response["folder_id"];
            if (response["new_inventory_item"].asUUID().notNull()) j.acknowledged["itemId"] = response["new_inventory_item"];
            if (response["new_asset"].asUUID().notNull()) j.acknowledged["assetId"] = response["new_asset"];
        }
        // Never forward HTTP diagnostics: they may contain capability URLs.
        check(j);
        require(bool(LLCoreHttpUtil::HttpCoroutineAdapter::getStatusFromLLSD(response[LLCoreHttpUtil::HttpCoroutineAdapter::HTTP_RESULTS])) &&
            !response.has("error") && !response.has("errors"), "server_error", "Server request failed or returned an invalid response.");
        return response;
    }
    LLSD fetch(Job& j, LLUUID folder);
    LLSD folderInfo(Job& j, LLUUID id);
    LLSD browse(Job& j, LLUUID id);
    LLSD createFolder(Job& j);
    LLSD trashFolder(Job& j);
    LLSD upload(Job& j, bool sound);
    LLSD objectInfo(Job& j, LLUUID id);
    LLSD taskInventory(Job& j, LLUUID id);
    LLSD deliver(Job& j);
    LLSD reconcile(Job& j);
    LLSD execute(Job& j);
    LLSD verifyItem(Job& j, LLUUID folder, LLUUID item, LLUUID asset, const std::string& type);
    LLSD find(const LLSD& rows, const LLUUID& id) {
        for (auto& row : llsd::inArray(rows)) if (row["id"].asUUID() == id) return row;
        return LLSD();
    }
    LLViewerObject* object(LLUUID id) {
        auto* obj = gObjectList.findObject(id);
        require(obj && !obj->isDead() && !obj->isAvatar() && !obj->isAttachment() && obj->getRegion() == gAgent.getRegion(),
            "object_unavailable", "Target must be a loaded rezzed prim in the current region."); return obj;
    }
    void watch(const LLSD& r);
    void events(const LLSD& r);
    void unwatch(const LLSD& r) { safe(r, [&] { activeLease(r); auto i = mWatches.find(r["watchId"].asString());
        if (i != mWatches.end()) { require(i->second.lease == mLease, "lease_required", "Watch belongs to another lease."); mWatches.erase(i); }
        return LLSD().with("ok", true); }); }
    void event(LLUUID id, LLSD value);
};

LLSD Assets::fetch(Job& j, LLUUID id) {
    LLSD body; body["folders"].append(LLSD().with("folder_id", id).with("owner_id", gAgent.getID())
        .with("fetch_folders", true).with("fetch_items", true).with("sort_order", 0));
    LLSD response = http(j, cap(j, "FetchInventoryDescendents2"), body);
    require((!response.has("bad_folders") || (response["bad_folders"].isArray() && response["bad_folders"].size() == 0)) &&
        response["folders"].isArray() && response["folders"].size() == 1, "inventory_incomplete", "Folder response is incomplete.");
    const auto& f = response["folders"][0];
    require(f["folder_id"].asUUID() == id && f["owner_id"].asUUID() == gAgent.getID() &&
        f["version"].isInteger() && f["version"].asInteger() >= 0 && f["descendents"].isInteger() &&
        fsmcp::completeInventory(f["owner_id"].asUUID() == gAgent.getID(), f["version"].asInteger(),
            f["descendents"].asInteger(), f["categories"].size(), f["items"].size()) &&
        (!f.has("categories") || f["categories"].isArray()) && (!f.has("items") || f["items"].isArray()) &&
        f["categories"].size() + f["items"].size() == f["descendents"].asInteger(), "inventory_incomplete", "Folder count, owner or version is inconsistent.");
    LLSD out = LLSD().with("id", id).with("ownerId", gAgent.getID()).with("version", f["version"])
        .with("complete", true).with("freshness", "server").with("folders", LLSD::emptyArray()).with("items", LLSD::emptyArray());
    std::set<LLUUID> ids;
    int processed = 0;
    for (const auto& c : llsd::inArray(f["categories"])) {
        LLUUID child = uuid(c.has("category_id") ? c["category_id"] : c["folder_id"]);
        require(child != id && ids.insert(child).second && c["parent_id"].asUUID() == id && c["name"].isString() &&
            c["type_default"].isInteger() && (!c.has("agent_id") || c["agent_id"].asUUID() == gAgent.getID()) &&
            (!c.has("owner_id") || c["owner_id"].asUUID() == gAgent.getID()), "inventory_incomplete", "Invalid folder metadata.");
        out["folders"].append(LLSD().with("id", child).with("parentId", id).with("ownerId", gAgent.getID())
            .with("name", c["name"]).with("folderType", c["type_default"])
            .with("folderTypeName", LLFolderType::lookup((LLFolderType::EType)c["type_default"].asInteger()))
            .with("isSystem", LLFolderType::lookupIsProtectedType((LLFolderType::EType)c["type_default"].asInteger())));
        if (++processed % 128 == 0) { llcoro::suspendUntilNextFrame(); check(j); }
    }
    for (const auto& data : llsd::inArray(f["items"])) {
        LLPointer<LLViewerInventoryItem> item = new LLViewerInventoryItem();
        require(data["permissions"].has("owner_mask") && data["permissions"]["owner_id"].asUUID() == gAgent.getID() &&
            data["agent_id"].asUUID() == gAgent.getID() && data["parent_id"].asUUID() == id && data["type"].isInteger() &&
            data["inv_type"].isInteger() && data["name"].isString() && data["name"].asString().size() <= 1024 &&
            data["desc"].isString() && data["desc"].asString().size() <= 1024 && item->unpackMessage(data) &&
            item->getUUID().notNull() && ids.insert(item->getUUID()).second && item->getParentUUID() == id &&
            item->getPermissions().getOwner() == gAgent.getID(), "inventory_incomplete", "Invalid inventory item metadata.");
        out["items"].append(itemRow(item));
        // Populate the viewer's cache from the same verified response, never use it as confirmation.
        gInventory.updateItem(item);
        if (++processed % 128 == 0) { llcoro::suspendUntilNextFrame(); check(j); }
    }
    gInventory.notifyObservers(); return out;
}

LLSD Assets::folderInfo(Job& j, LLUUID id) {
    check(j);
    auto* cat = gInventory.getCategory(id);
    require(cat && cat->getOwnerID() == gAgent.getID() && cachedPath(id)["pathComplete"].asBoolean(),
        "folder_unverified", "Folder is not known under this avatar's inventory root; refresh its parent first.");
    if (id == gInventory.getRootFolderID()) return LLSD().with("id", id).with("parentId", LLUUID::null).with("name", cat->getName())
        .with("ownerId", gAgent.getID()).with("folderType", (int)cat->getPreferredType()).with("isSystem", true);
    LLSD parent = fetch(j, cat->getParentUUID()); LLSD row = find(parent["folders"], id);
    require(row.isMap(), "folder_unverified", "Fresh parent contents did not confirm this folder."); return row;
}
LLSD Assets::browse(Job& j, LLUUID id) {
    LLSD meta = folderInfo(j, id); LLSD out = fetch(j, id);
    for (auto it = meta.beginMap(); it != meta.endMap(); ++it) out[it->first] = it->second;
    if (id != gInventory.getRootFolderID()) {
        LLPointer<LLViewerInventoryCategory> category = new LLViewerInventoryCategory(id, meta["parentId"].asUUID(),
            (LLFolderType::EType)meta["folderType"].asInteger(), meta["name"].asString(), gAgent.getID());
        gInventory.updateCategory(category);
    }
    auto display = cachedPath(id);
    for (auto it = display.beginMap(); it != display.endMap(); ++it) out[it->first] = it->second;
    // Cache verified child categories so the next explicit child browse can resolve its parent.
    for (auto& row : llsd::inArray(out["folders"])) {
        LLPointer<LLViewerInventoryCategory> category = new LLViewerInventoryCategory(row["id"].asUUID(), id,
            (LLFolderType::EType)row["folderType"].asInteger(), row["name"].asString(), gAgent.getID());
        gInventory.updateCategory(category);
    }
    for (int i = 0; i < out["folders"].size(); ++i) {
        out["folders"][i]["path"] = cachedPath(out["folders"][i]["id"].asUUID())["path"];
        if (i % 128 == 0) { llcoro::suspendUntilNextFrame(); check(j); }
    }
    return out;
}
LLSD Assets::createFolder(Job& j) {
    LLUUID parent = uuid(j.args["parentId"]), requested = uuid(j.args["folderId"]);
    require(parent != requested, "invalid_request", "Folder and parent must differ.");
    boundedText(j.args["name"], 63); folderInfo(j, parent);
    LLSD before = fetch(j, parent);
    for (auto& row : llsd::inArray(before["folders"])) require(row["id"].asUUID() != requested && row["name"] != j.args["name"],
        "folder_conflict", "An existing folder conflicts with this creation intent; it was not adopted.");
    auto url = cap(j, "CreateInventoryCategory"); check(j, true); j.submitted = true; j.phase = "submitted";
    LLSD reply = http(j, url, LLSD().with("folder_id", requested).with("parent_id", parent).with("type", -1).with("name", j.args["name"]));
    LLUUID actual = uuid(reply["folder_id"]); j.acknowledged["folderId"] = actual;
    require(actual != parent && reply["parent_id"].asUUID() == parent && reply["name"] == j.args["name"] &&
        reply["type"].isInteger() && reply["type"].asInteger() == -1, "folder_ack_invalid", "Server folder acknowledgement changed identity or metadata.");
    j.phase = "confirming";
    for (int i = 0; i < 12; ++i) {
        LLSD found = find(fetch(j, parent)["folders"], actual);
        if (found.isMap()) {
            require(found["name"] == j.args["name"] && found["folderType"].asInteger() == -1, "folder_conflict", "Confirmed folder metadata differs.");
            LLPointer<LLViewerInventoryCategory> cat = new LLViewerInventoryCategory(actual, parent, LLFolderType::FT_NONE,
                found["name"].asString(), gAgent.getID()); gInventory.updateCategory(cat); gInventory.notifyObservers();
            found["requestedId"] = requested; found["folderIdMatchesRequested"] = actual == requested; found["freshness"] = "server";
            return found;
        }
        llcoro::suspendUntilTimeout(.5f); check(j);
    }
    throw Failure("folder_unconfirmed", "Server acknowledged a folder but fresh contents have not confirmed it.");
}
LLSD Assets::trashFolder(Job& j) {
    LLUUID id = uuid(j.args["folderId"]), parent = uuid(j.args["parentFolderId"]);
    // Receipt is injected only by the bridge from its durable confirmed creation.
    // Consumer-supplied receipts are rejected by the bridge even via viewer_call.
    const auto receipt = j.args["creationReceipt"];
    require(receipt["kind"].asString() == "createFolder" && receipt["result"]["id"].asUUID() == id &&
        receipt["arguments"]["parentId"].asUUID() == parent && receipt["arguments"]["name"] == j.args["name"] &&
        receipt["expected"]["avatarId"] == j.expected["avatarId"] && receipt["expected"]["grid"] == j.expected["grid"],
        "creation_unverified", "Cleanup requires a journaled confirmed creation for this exact folder.");
    auto root = fetch(j, gInventory.getRootFolderID()); LLUUID trash;
    for (auto& f : llsd::inArray(root["folders"])) if (f["folderType"].asInteger() == LLFolderType::FT_TRASH) {
        require(trash.isNull(), "trash_unavailable", "Trash is ambiguous."); trash = f["id"].asUUID();
    }
    require(trash.notNull() && id != trash && parent != trash && id != gInventory.getRootFolderID(), "trash_unavailable", "Cleanup target or Trash is invalid.");
    LLSD original = find(fetch(j, parent)["folders"], id), moved = find(fetch(j, trash)["folders"], id);
    auto response = LLSD().with("folderId", id).with("parentFolderId", parent).with("trashFolderId", trash).with("name", j.args["name"]);
    if (original.isUndefined() && moved.isMap() && moved["name"] == j.args["name"] && moved["folderType"].asInteger() == -1)
        return response.with("trashed", true).with("noop", true);
    require(original.isMap() && original["name"] == j.args["name"] && original["folderType"].asInteger() == -1,
        "folder_conflict", "Cleanup folder has moved or changed.");
    if (j.args["inspectOnly"].asBoolean()) return response.with("trashed", false).with("noop", true);
    LLSD contents = fetch(j, id);
    require(contents["folders"].size() == 0 && contents["items"].size() == 0, "folder_not_empty", "Cleanup only accepts a freshly verified empty folder.");
    check(j, true); j.submitted = true; j.phase = "submitted";
    LLMessageSystem* msg = gMessageSystem; msg->newMessage("MoveInventoryFolder"); msg->nextBlock("AgentData");
    msg->addUUID("AgentID", gAgent.getID()); msg->addUUID("SessionID", gAgent.getSessionID()); msg->addBOOL("Stamp", true);
    msg->nextBlock("InventoryData"); msg->addUUID("FolderID", id); msg->addUUID("ParentID", trash); gAgent.sendReliableMessage();
    for (int i = 0; i < 12; ++i) {
        original = find(fetch(j, parent)["folders"], id); moved = find(fetch(j, trash)["folders"], id);
        if (original.isUndefined() && moved.isMap() && moved["name"] == j.args["name"]) return response.with("trashed", true).with("noop", false);
        llcoro::suspendUntilTimeout(.5f); check(j);
    }
    throw Failure("folder_unconfirmed", "Move was sent but has not been confirmed in Trash.");
}

LLSD Assets::verifyItem(Job& j, LLUUID folder, LLUUID id, LLUUID asset, const std::string& type) {
    j.phase = "confirming";
    for (int i = 0; i < 12; ++i) {
        auto row = find(fetch(j, folder)["items"], id);
        if (row.isMap() && row["assetId"].asUUID() == asset) {
            require(row["name"] == j.args["name"] && row["description"] == j.args["description"] && row["assetType"].asString() == type,
                "item_conflict", "Item metadata differs from the submitted intent.");
            return LLSD().with("itemId", id).with("assetId", asset).with("freshness", "server");
        }
        llcoro::suspendUntilTimeout(.5f); check(j);
    }
    throw Failure("item_unconfirmed", "Upload was acknowledged but fresh inventory has not confirmed its item and asset.");
}

LLSD Assets::upload(Job& j, bool sound) {
    boundedText(j.args["name"], 63); boundedText(j.args["description"], 255);
    LLUUID folder = uuid(j.args["folderId"]); folderInfo(j, folder);
    LLSD listing = fetch(j, folder); LLUUID item;
    std::string bytes;
    if (sound) {
        require(j.args["expectedCost"].isInteger() && j.args["expectedCost"].asInteger() == 0 &&
            (grid() == "agni" || grid() == "aditi") && soundCost() == 0,
            "cost_not_zero", "Sound upload requires known zero account benefits and expectedCost: 0.");
        bytes = std::move(j.bytes);
        auto valid = std::async(std::launch::async, [&bytes] { return fsmcp::validateSound(bytes); });
        // Always join only a completed worker. No viewer data crosses this boundary.
        while (valid.wait_for(std::chrono::seconds(0)) != std::future_status::ready) llcoro::suspendUntilNextFrame();
        require(valid.get(), "invalid_audio", "Payload did not decode as bounded mono 44.1 kHz Ogg Vorbis."); check(j, true);
    } else {
        boundedText(j.args["text"], 65536, true);
        auto serialized = std::async(std::launch::async, [text = j.args["text"].asString()] {
            LLNotecard card; card.setText(text); std::ostringstream stream;
            if (!card.exportStream(stream)) throw Failure("invalid_notecard", "Viewer notecard serialization failed.");
            return stream.str();
        });
        while (serialized.wait_for(std::chrono::seconds(0)) != std::future_status::ready) llcoro::suspendUntilNextFrame();
        bytes = serialized.get(); check(j, true);
        if (j.args.has("existingItemId")) {
            item = uuid(j.args["existingItemId"]); auto row = find(listing["items"], item);
            require(row.isMap() && row["assetType"].asString() == "notecard" && row["inventoryType"].asString() == "notecard" &&
                row["name"] == j.args["name"] && row["description"] == j.args["description"] && row["canModify"].asBoolean(),
                "permission_denied", "Existing notecard identity, ownership or modify permission was not verified.");
        }
    }
    if (item.isNull()) for (auto& row : llsd::inArray(listing["items"])) require(row["description"] != j.args["description"],
        "marker_conflict", "An item already has this description marker. Reconcile instead of creating another.");
    std::string url = cap(j, sound ? "NewFileAgentInventory" : "UpdateNotecardAgentInventory");
    if (!sound && item.isNull()) {
        auto created = std::make_shared<LLUUID>();
        std::weak_ptr<Job> pending = mJobs.at(j.id);
        LLPointer<LLInventoryCallback> cb = new LLBoostFuncInventoryCallback([created, pending](const LLUUID& id) {
            *created = id;
            if (auto job = pending.lock()) if (id.notNull()) job->acknowledged["itemId"] = id;
        });
        check(j, true); j.submitted = true; j.phase = "creating_item";
        create_inventory_item(gAgent.getID(), gAgent.getSessionID(), folder, LLTransactionID::tnull, j.args["name"].asString(),
            j.args["description"].asString(), LLAssetType::AT_NOTECARD, LLInventoryType::IT_NOTECARD, NO_INV_SUBTYPE, PERM_ALL, cb);
        double until = now() + 25;
        while (created->isNull() && now() < until) { llcoro::suspendUntilTimeout(.1f); check(j); }
        require(created->notNull(), "item_unconfirmed", "Notecard creation was sent but no item was acknowledged.");
        item = *created; j.acknowledged["itemId"] = item;
        auto row = find(fetch(j, folder)["items"], item);
        require(row.isMap() && row["name"] == j.args["name"] && row["description"] == j.args["description"] &&
            row["assetType"].asString() == "notecard" && row["canModify"].asBoolean(), "item_unconfirmed", "Created notecard metadata is unconfirmed.");
    }
    LLSD body;
    if (sound) body = LLSD().with("folder_id", folder).with("asset_type", "sound").with("inventory_type", "sound")
        .with("name", j.args["name"]).with("description", j.args["description"]).with("next_owner_mask", (int)PERM_ALL)
        .with("group_mask", 0).with("everyone_mask", 0).with("expected_upload_cost", 0);
    else body["item_id"] = item;
    check(j, true); j.phase = "quoting";
    LLSD quote = http(j, url, body);
    require(quote["state"].asString() == "upload" && !quote["uploader"].asString().empty(), "quote_invalid", "Server did not return an upload invitation.");
    if (sound) require(fsmcp::zeroCost(j.args["expectedCost"].asInteger(), soundCost(),
        quote["upload_price"].isInteger() ? std::optional<int>(quote["upload_price"].asInteger()) : std::nullopt),
        "cost_not_zero", "Server quote is missing, changed or nonzero; no sound bytes were sent.");
    check(j, true);
    LLSD completed = http(j, quote["uploader"].asString(), LLSD(), false, &bytes);
    if (sound && completed.has("upload_price")) require(completed["upload_price"].isInteger() && completed["upload_price"].asInteger() == 0,
        "cost_changed_after_submit", "Server changed the price after a zero quote; outcome requires inspection.");
    require(completed["state"].asString() == "complete", "upload_unconfirmed", "Asset submission has not been confirmed complete.");
    LLUUID asset = uuid(completed["new_asset"]); if (sound) item = uuid(completed["new_inventory_item"]);
    j.acknowledged["itemId"] = item; j.acknowledged["assetId"] = asset;
    // Use the existing viewer completion workflow for notecard cache invalidation.
    // The bounded HTTP path above is separate from the legacy ungated EnqueueInventoryUpload.
    if (!sound) {
        LLBufferedAssetUploadInfo info(item, LLAssetType::AT_NOTECARD, bytes, LLBufferedAssetUploadInfo::invnUploadFinish_f(), LLBufferedAssetUploadInfo::uploadFailed_f());
        info.finishUpload(completed);
    }
    return verifyItem(j, folder, item, asset, sound ? "sound" : "notecard");
}

void Assets::properties(LLMessageSystem* msg) {
    LLUUID id, owner; msg->getUUID("ObjectData", "ObjectID", id); msg->getUUID("ObjectData", "OwnerID", owner);
    auto pending = mProperties.find(id); if (pending == mProperties.end() || !gAgent.getRegion() || msg->getSender() != gAgent.getRegion()->getHost()) return;
    std::string name; msg->getString("ObjectData", "Name", name);
    pending->second = LLSD().with("ownerId", owner).with("name", name.substr(0, 256)).with("generation", mGeneration);
}
LLSD Assets::objectInfo(Job& j, LLUUID id) {
    check(j); auto* obj = object(id); mProperties[id] = LLSD();
    LLSelectMgr::getInstance()->requestObjectPropertiesFamily(obj);
    double until = now() + 10;
    while (mProperties[id].isUndefined() && now() < until) { llcoro::suspendUntilTimeout(.1f); check(j); }
    LLSD props = mProperties[id]; mProperties.erase(id);
    require(props.isMap() && props["ownerId"].asUUID() == gAgent.getID() && props["generation"].asString() == mGeneration,
        "ownership_unverified", "Fresh object properties did not verify this avatar as owner.");
    obj = object(id);
    return LLSD().with("objectId", id).with("ownerId", props["ownerId"]).with("name", props["name"])
        .with("region", gAgent.getRegion()->getName()).with("regionId", gAgent.getRegion()->getRegionID())
        .with("hoverText", obj->mHudText.substr(0,8192)).with("position", ll_sd_from_vector3(obj->getPositionRegion()))
        .with("canModify", obj->permModify()).with("canCopy", obj->permCopy()).with("isAttachment", false)
        .with("ownershipFreshness", "server").with("sceneFreshness", "viewer_cache");
}
LLSD Assets::taskInventory(Job& j, LLUUID id) {
    objectInfo(j, id);
    // Omit inventory_serial deliberately: a 304 or local cache cannot prove emptiness.
    LLSD response = http(j, cap(j, "RequestTaskInventory") + "?task_id=" + id.asString(), LLSD(), true);
    object(id);
    require(response["contents"].isArray() && response["contents"].size() <= (int)MAX_ROWS && response["inventory_serial"].isInteger(),
        "task_inventory_incomplete", "Fresh complete task inventory is unavailable.");
    LLSD out = LLSD().with("objectId", id).with("freshness", "server").with("complete", true)
        .with("serial", response["inventory_serial"]).with("items", LLSD::emptyArray());
    std::set<LLUUID> seen;
    for (auto& data : llsd::inArray(response["contents"])) {
        LLPointer<LLViewerInventoryItem> item = new LLViewerInventoryItem;
        require(data.has("permissions") && data.has("type") && data.has("inv_type") && item->unpackMessage(data) &&
            item->getUUID().notNull() && seen.insert(item->getUUID()).second, "task_inventory_incomplete", "Task item metadata is incomplete.");
        out["items"].append(itemRow(item));
    }
    return out;
}
LLSD Assets::deliver(Job& j) {
    LLUUID target = uuid(j.args["objectId"]), id = uuid(j.args["itemId"]), folder = uuid(j.args["folderId"]);
    folderInfo(j, folder); auto row = find(fetch(j, folder)["items"], id);
    require(row.isMap() && fsmcp::canDeliver(row["ownerId"].asUUID() == gAgent.getID(), row["groupOwned"].asBoolean(),
        row["canCopy"].asBoolean(), row["assetId"].asUUID().notNull()), "permission_denied", "Delivery requires an owned, populated, copyable inventory item.");
    auto inv = taskInventory(j, target);
    auto matches = [&](const LLSD& value) { return value["assetId"] == row["assetId"] && value["name"] == row["name"] &&
        value["description"] == row["description"] && value["assetType"] == row["assetType"] && value["ownerId"] == row["ownerId"]; };
    for (auto& existing : llsd::inArray(inv["items"])) if (matches(existing)) return LLSD().with("delivered", true).with("noop", true)
        .with("itemId", existing["id"]).with("assetId", row["assetId"]).with("freshness", "server");
    objectInfo(j, target); auto* obj = object(target);
    require(obj->permModify(), "permission_denied", "Target object is not modifiable by its owner.");
    // Re-fetch source immediately before dispatch; don't trust optimistic local permission updates.
    auto current = find(fetch(j, folder)["items"], id);
    require(current == row && current["canCopy"].asBoolean(), "item_conflict", "Source item changed before delivery.");
    obj = object(target); auto* source = gInventory.getItem(id);
    require(source && source->getPermissions().allowCopyBy(gAgent.getID()), "permission_denied", "Source copy permission changed.");
    check(j, true); j.submitted = true; j.phase = "submitted";
    LLPointer<LLViewerInventoryItem> copy = new LLViewerInventoryItem(source);
    obj->updateInventory(copy, TASK_INVENTORY_ITEM_KEY, true);
    for (int i = 0; i < 12; ++i) {
        inv = taskInventory(j, target);
        for (auto& item : llsd::inArray(inv["items"])) if (matches(item)) return LLSD().with("delivered", true)
            .with("itemId", item["id"]).with("assetId", item["assetId"]).with("freshness", "server");
        llcoro::suspendUntilTimeout(.5f); check(j);
    }
    throw Failure("delivery_unconfirmed", "Delivery was dispatched but matching task inventory has not arrived.");
}

void Assets::watch(const LLSD& r) { safe(r, [&] {
    observe(); activeLease(r); require(mWatches.size() < 8, "watch_limit", "Object watch capacity reached.");
    Job j; j.expected = r["expected"]; j.lease = mLease; check(j, true);
    LLUUID id = uuid(r["objectId"]); auto* obj = object(id);
    require(obj->permYouOwner(), "ownership_unverified", "Only owned loaded objects can be watched.");
    std::string watchId = LLUUID::generateNewID().asString();
    mWatches.emplace(watchId, Watch{id, mLease, mGeneration, now() + llclamp(r["seconds"].asReal(), 1., 180.)});
    return LLSD().with("ok", true).with("watchId", watchId).with("cursor", 0);
}); }
void Assets::events(const LLSD& r) { safe(r, [&] {
    observe(); activeLease(r); auto i = mWatches.find(r["watchId"].asString());
    require(i != mWatches.end() && i->second.lease == mLease, "watch_missing", "Watch expired or belongs to another lease.");
    auto& watch = i->second; int after = r["after"].asInteger(); LLSD entries = LLSD::emptyArray();
    for (auto& e : watch.events) if (e["cursor"].asInteger() > after) entries.append(e);
    bool dropped = !watch.events.empty() && after < watch.events.front()["cursor"].asInteger() - 1;
    return LLSD().with("ok", true).with("events", entries).with("cursor", watch.cursor).with("dropped", dropped);
}); }
void Assets::event(LLUUID id, LLSD value) {
    observe();
    for (auto& entry : mWatches) if (entry.second.object == id && entry.second.generation == mGeneration) {
        auto& watch = entry.second; value["cursor"] = ++watch.cursor; value["generation"] = mGeneration;
        if (watch.events.size() == 64) watch.events.pop_front(); watch.events.push_back(value);
    }
}
void Assets::chat(LLMessageSystem* msg) {
    if (mWatches.empty() || !gAgent.getRegion() || msg->getSender() != gAgent.getRegion()->getHost()) return;
    LLUUID source, owner; U8 type, origin; std::string message;
    msg->getUUID("ChatData", "SourceID", source); msg->getUUID("ChatData", "OwnerID", owner);
    msg->getU8("ChatData", "SourceType", origin); msg->getU8("ChatData", "ChatType", type);
    if (owner != gAgent.getID() || origin != CHAT_SOURCE_OBJECT || type != CHAT_TYPE_OWNER) return;
    bool wanted = false; for (auto& w : mWatches) if (w.second.object == source) wanted = true;
    if (!wanted) return;
    msg->getString("ChatData", "Message", message); if (message.size() > 4096) return;
    event(source, LLSD().with("type", "ownerChat").with("objectId", source).with("ownerId", owner).with("message", message));
}
void Assets::dialog(LLMessageSystem* msg) {
    if (mWatches.empty() || !gAgent.getRegion() || msg->getSender() != gAgent.getRegion()->getHost()) return;
    LLUUID source, owner; msg->getUUID("Data", "ObjectID", source);
    if (msg->getNumberOfBlocks("OwnerData") == 0) return; msg->getUUID("OwnerData", "OwnerID", owner);
    if (owner != gAgent.getID()) return;
    bool wanted = false; for (auto& w : mWatches) if (w.second.object == source) wanted = true; if (!wanted) return;
    int channel; std::string message; msg->getS32("Data", "ChatChannel", channel); msg->getString("Data", "Message", message);
    int count = msg->getNumberOfBlocks("Buttons"); if (message.size() > 4096 || count < 1 || count > 12) return;
    LLSD buttons = LLSD::emptyArray(); for (int i = 0; i < count; ++i) { std::string button; msg->getString("Buttons", "ButtonLabel", button, i); if (button.size() > 64) return; buttons.append(button); }
    event(source, LLSD().with("type", "dialog").with("objectId", source).with("ownerId", owner).with("message", message)
        .with("buttons", buttons).with("channel", channel).with("dialogId", LLUUID::generateNewID()).with("received", now()));
}

LLSD Assets::reconcile(Job& j) {
    const auto intent = j.args["intent"]; const std::string kind = intent["kind"].asString(); const auto a = intent["arguments"];
    require(intent["expected"]["avatarId"] == j.expected["avatarId"] && intent["expected"]["grid"] == j.expected["grid"],
        "session_changed", "Reconciliation belongs to a different account or grid.");
    if (kind == "createFolder") {
        auto acknowledged = intent["acknowledged"]["folderId"].asUUID();
        require(acknowledged.notNull(), "outcome_unknown", "No server folder UUID was retained; do not adopt a same-name folder or replay creation.");
        LLSD row = find(fetch(j, uuid(a["parentId"]))["folders"], acknowledged);
        require(row.isMap() && row["name"] == a["name"] && row["folderType"].asInteger() == -1,
            "outcome_unknown", "Acknowledged folder has not been confirmed; absence does not authorize replay.");
        return row.with("requestedId", a["folderId"]).with("folderIdMatchesRequested", acknowledged == a["folderId"].asUUID()).with("freshness", "server");
    }
    if (kind == "uploadSound" || kind == "createNotecard") {
        auto listing = fetch(j, uuid(a["folderId"])); LLSD match; int count = 0;
        for (auto& item : llsd::inArray(listing["items"])) if (item["description"] == a["description"]) { match = item; ++count; }
        require(count == 1 && match["name"] == a["name"] && match["assetType"].asString() == (kind == "uploadSound" ? "sound" : "notecard") &&
            match["assetId"].asUUID().notNull(), "outcome_unknown", "No unique populated item confirms the saved marker; do not replay automatically.");
        auto ack = intent["acknowledged"];
        require((!ack.has("itemId") || ack["itemId"].asUUID() == match["id"].asUUID()) &&
            (!ack.has("assetId") || ack["assetId"].asUUID() == match["assetId"].asUUID()),
            "item_conflict", "Saved acknowledgement disagrees with the marker.");
        // An existing notecard's nonzero asset may predate the interrupted update.
        require(kind != "createNotecard" || ack["assetId"].asUUID().notNull(), "outcome_unknown", "Notecard content completion lacks an acknowledged asset; retry only by explicit verified-item update.");
        return LLSD().with("itemId", match["id"]).with("assetId", match["assetId"]).with("freshness", "server");
    }
    throw Failure("outcome_unknown", "Inspect fresh inventory/object events for this operation; automatic replay is disabled.");
}

LLSD Assets::execute(Job& j) {
    if (j.kind == "listInventory") return browse(j, j.args.has("folderId") ? uuid(j.args["folderId"]) : gInventory.getRootFolderID());
    if (j.kind == "searchFolders") {
        boundedText(j.args["query"], 128); std::string query = j.args["query"].asString(); LLStringUtil::toLower(query);
        int max = llclamp(j.args["maxResults"].asInteger(), 1, 200); LLSD rows = LLSD::emptyArray();
        std::vector<LLUUID> pending{gInventory.getRootFolderID()}; std::set<LLUUID> visited;
        size_t examined = 0; bool limited = false;
        while (examined < pending.size() && rows.size() < max) {
            LLUUID id = pending[examined++];
            if (!visited.insert(id).second) continue;
            auto* cat = gInventory.getCategory(id);
            if (!cat || cat->getOwnerID() != gAgent.getID()) continue;
            std::string name = cat->getName(); LLStringUtil::toLower(name);
            if (name.find(query) != std::string::npos) rows.append(LLSD().with("id", cat->getUUID()).with("parentId", cat->getParentUUID())
                .with("name", cat->getName()).with("folderType", (int)cat->getPreferredType()).with("ownerId", cat->getOwnerID())
                .with("folderTypeName", LLFolderType::lookup(cat->getPreferredType())).with("isSystem", LLFolderType::lookupIsProtectedType(cat->getPreferredType()))
                .with("path", cachedPath(id)["path"]));
            LLInventoryModel::cat_array_t* children; LLInventoryModel::item_array_t* ignored;
            gInventory.getDirectDescendentsOf(id, children, ignored);
            if (children) for (auto& child : *children) {
                if (pending.size() == 20000) { limited = true; break; }
                pending.push_back(child->getUUID());
            }
            if (examined % 128 == 0) { llcoro::suspendUntilNextFrame(); check(j); }
        }
        return LLSD().with("folders", rows).with("freshness", "cache").with("complete", false).with("limited", limited || rows.size() == max)
            .with("totalMatches", rows.size()).with("totalMatchesExact", false).with("truncated", limited || rows.size() == max);
    }
    if (j.kind == "createFolder") return createFolder(j);
    if (j.kind == "trashEmptyFolder") return trashFolder(j);
    if (j.kind == "uploadSound") return upload(j, true);
    if (j.kind == "createNotecard") return upload(j, false);
    if (j.kind == "objectInfo") return objectInfo(j, uuid(j.args["objectId"]));
    if (j.kind == "taskInventory") return taskInventory(j, uuid(j.args["objectId"]));
    if (j.kind == "deliverItem") return deliver(j);
    if (j.kind == "reconcile") return reconcile(j);
    if (j.kind == "touch") {
        LLUUID id = uuid(j.args["objectId"]); objectInfo(j, id); auto* obj = object(id);
        int face = j.args["face"].asInteger(); require(face >= 0 && face < obj->getNumTEs(), "invalid_request", "Face is outside the prim's texture entries.");
        check(j, true); j.submitted = true; LLPickInfo pick; pick.mObjectFace = face;
        send_ObjectGrab_message(obj, pick, LLVector3::zero); send_ObjectDeGrab_message(obj, pick);
        return LLSD().with("dispatched", true).with("verifiedEffect", false);
    }
    if (j.kind == "dialogReply") {
        LLSD dialog; std::string dialogId = j.args["dialogId"].asString();
        for (auto& w : mWatches) if (w.second.lease == j.lease) for (auto& e : w.second.events)
            if (e["type"].asString() == "dialog" && e["dialogId"].asString() == dialogId) dialog = e;
        require(dialog.isMap() && !dialog["responded"].asBoolean() && now() - dialog["received"].asReal() < 120 &&
            dialog["generation"].asString() == mGeneration && dialog["objectId"].asUUID() == j.args["objectId"].asUUID(),
            "dialog_stale", "Dialog is missing, expired, answered or from another object/session.");
        int index = j.args["buttonIndex"].asInteger();
        require(j.args["buttonIndex"].isInteger() && index >= 0 && index < dialog["buttons"].size() &&
            dialog["buttons"][index] == j.args["buttonLabel"], "dialog_mismatch", "Button index and label must match the received dialog.");
        objectInfo(j, uuid(dialog["objectId"])); check(j, true);
        bool stillPending = false;
        for (auto& w : mWatches) if (w.second.lease == j.lease) for (auto& e : w.second.events)
            if (e["dialogId"].asString() == dialogId && !e["responded"].asBoolean() && now() - e["received"].asReal() < 120) stillPending = true;
        require(stillPending, "dialog_stale", "Dialog was answered or expired during ownership verification.");
        j.submitted = true;
        // Mark all copies before dispatch; a different request ID cannot answer it twice.
        for (auto& w : mWatches) for (auto& e : w.second.events) if (e["dialogId"].asString() == dialogId) e["responded"] = true;
        LLMessageSystem* msg = gMessageSystem; msg->newMessage("ScriptDialogReply"); msg->nextBlock("AgentData");
        msg->addUUID("AgentID", gAgent.getID()); msg->addUUID("SessionID", gAgent.getSessionID()); msg->nextBlock("Data");
        msg->addUUID("ObjectID", dialog["objectId"].asUUID()); msg->addS32("ChatChannel", dialog["channel"].asInteger());
        msg->addS32("ButtonIndex", index); msg->addString("ButtonLabel", j.args["buttonLabel"].asString()); msg->sendReliable(gAgent.getRegion()->getHost());
        return LLSD().with("dispatched", true).with("verifiedEffect", false);
    }
    throw Failure("unsupported_operation", "Unsupported asset operation.");
}

Assets* instance = nullptr;
} // namespace

void initFSMCPAssets() { static Assets assets; instance = &assets; }
void fsmcpAssetsProperties(LLMessageSystem* msg) { if (instance) instance->properties(msg); }
void fsmcpAssetsChat(LLMessageSystem* msg) { if (instance) instance->chat(msg); }
void fsmcpAssetsDialog(LLMessageSystem* msg) { if (instance) instance->dialog(msg); }
void fsmcpAssetsDialogAnswered(const LLUUID& object, int channel) { if (instance) instance->answered(object, channel); }
void fsmcpAssetsLoginBenefits(const LLUUID& avatar, const LLSD& cost) { if (instance) instance->loginBenefits(avatar, cost); }
