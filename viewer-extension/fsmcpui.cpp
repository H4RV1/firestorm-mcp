// SPDX-License-Identifier: MIT
// Bounded, read-only UI observations. No recursive selectors or UI input.
#include "llviewerprecompiledheaders.h"
#include "fsmcpui.h"
#include "lleventapi.h"
#include "llui.h"
#include "llview.h"
#include "lluictrl.h"
#include "lllineeditor.h"
#include "llscrolllistctrl.h"
#include "llscrolllistitem.h"
#include "llscrolllistcell.h"
#include "lluri.h"
#include "llsdutil.h"
#include <chrono>
#include <functional>
#include <stdexcept>

namespace
{
std::string exactPath(LLView* view)
{
    std::vector<std::string> names;
    for (; view && view->getParent(); view = view->getParent())
    {
        if (names.size() >= 80) throw std::runtime_error("UI path depth exceeded");
        names.push_back(LLURI::escape(view->getName(), "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~ "));
    }
    std::string path;
    for (auto it = names.rbegin(); it != names.rend(); ++it) path += "/" + *it;
    return path;
}
S32 bound(const LLSD& r, const char* key, S32 fallback, S32 low, S32 high)
{
    if (!r.has(key)) return fallback;
    if (!r[key].isInteger() || r[key].asInteger() < low || r[key].asInteger() > high)
        throw std::runtime_error(std::string("Invalid bounded field: ") + key);
    return r[key].asInteger();
}

LLView* exactView(const std::string& path)
{
    if (path.empty() || path.size() > 2048 || path.front() != '/' || path.back() == '/' || path.find("//") != std::string::npos)
        throw std::runtime_error("Use a bounded exact absolute UI path");
    LLView* view = LLUI::getInstance()->getRootView();
    size_t start = 1, scanned = 0, depth = 0;
    while (start < path.size())
    {
        size_t end = path.find('/', start);
        std::string name = LLURI::unescape(path.substr(start, end == std::string::npos ? end : end - start));
        if (++depth > 80) throw std::runtime_error("UI path depth exceeded");
        LLView* match = nullptr;
        for (LLView* child : *view->getChildList())
        {
            if (++scanned > 8192) throw std::runtime_error("UI resolution budget exceeded");
            if (child->getName() == name)
            {
                if (match) throw std::runtime_error("Ambiguous UI path; multiple runtime instances share this name");
                match = child;
            }
        }
        if (!match) throw std::runtime_error("UI path is unavailable");
        view = match;
        if (end == std::string::npos) break;
        start = end + 1;
    }
    return view;
}

// Construct metadata without getInfo(): virtual LLUICtrl::addInfo would
// fetch a potentially huge script/chat value even for metadata-only requests.
LLSD observation(LLView* view, bool values, S32 max_bytes)
{
    LLSD result;
    result["path"] = exactPath(view);
    result["class"] = typeid(*view).name();
    result["visible"] = view->getVisible(); result["enabled"] = view->getEnabled();
    result["visible_chain"] = view->isInVisibleChain(); result["enabled_chain"] = view->isInEnabledChain();
    result["available"] = view->isAvailable();
    LLRect rect = view->calcScreenRect();
    result["rect"] = LLSD().with("left", rect.mLeft).with("top", rect.mTop).with("right", rect.mRight).with("bottom", rect.mBottom);
    result["value_available"] = false;
    if (!values || !view->isInVisibleChain()) return result;
    auto control = dynamic_cast<LLUICtrl*>(view);
    if (!control) return result;
    auto line = dynamic_cast<LLLineEditor*>(view);
    // This baseline has no public password-state getter. Fail closed for line
    // editors instead of exposing password fields through a generic value read.
    if (line) { result["value_reason"] = "line_editor_value_not_exposed"; return result; }
    LLSD value = control->getValue();
    if (value.isMap() || value.isArray() || value.isBinary())
        result["value_reason"] = "structured_value_not_exposed";
    else if (value.isString() && value.asString().size() > max_bytes)
    {
        result["value_reason"] = "value_exceeds_byte_limit";
        result["value_truncated"] = true;
    }
    else { result["value"] = value; result["value_available"] = true; }
    return result;
}

class FSMCPUI final : public LLEventAPI
{
public:
    FSMCPUI() : LLEventAPI("FSMCPUI", "Bounded UI observations, schema version 1")
    {
        add("getPaths", "Bounded shallow UI paths under an exact path. limit<=200, max_depth<=8; truncated is not complete.",
            &FSMCPUI::getPaths, LLSD().with("reply", LLSD()).with("under", LLSD()));
        add("getControls", "Read 1-20 exact paths in one event-loop turn. Optional include_values and max_bytes<=4096.",
            &FSMCPUI::getControls, LLSD().with("reply", LLSD()).with("paths", LLSD()));
        add("getRows", "Read a visible scroll list (compiler messages etc.), <=50 rows and <=8 columns. No input.",
            &FSMCPUI::getRows, LLSD().with("reply", LLSD()).with("path", LLSD()));
    }
private:
    void getPaths(const LLSD& r)
    {
        Response response(LLSD(), r);
        try
        {
            S32 limit = bound(r, "limit", 100, 1, 200), max_depth = bound(r, "max_depth", 2, 0, 8);
            S32 offset = bound(r, "offset", 0, 0, 2048), visited = 0, skipped = 0, bytes = 0;
            auto started = std::chrono::steady_clock::now();
            response["schema_version"] = 1;
            response["paths"] = LLSD::emptyArray();
            bool stopped = false, depth_limited = false;
            std::function<void(LLView*, S32)> visit = [&](LLView* view, S32 depth)
            {
                if (stopped) return;
                if (visited >= 2048 || std::chrono::steady_clock::now() - started > std::chrono::milliseconds(8))
                { stopped = true; return; }
                ++visited;
                if (skipped++ >= offset)
                {
                    std::string path = exactPath(view);
                    if (response["paths"].size() >= limit || bytes + path.size() > 65536 || path.size() > 2048)
                    { --visited; stopped = true; return; }
                    bytes += (S32)path.size();
                    response["paths"].append(path);
                }
                if (depth == max_depth) { depth_limited |= !view->getChildList()->empty(); return; }
                for (LLView* child : *view->getChildList()) { visit(child, depth + 1); if (stopped) break; }
            };
            visit(exactView(r["under"].asString()), 0);
            response["visited"] = visited;
            response["truncated"] = stopped;
            response["depth_limited"] = depth_limited;
            response["next_offset"] = stopped && visited > offset && visited < 2048 ? LLSD(visited) : LLSD();
            response["pagination_consistency"] = "live_query_per_page_not_a_snapshot";
            response["bounded_in_viewer"] = true;
        }
        catch (const std::exception& e) { response.error(e.what()); }
    }
    void getControls(const LLSD& r)
    {
        Response response(LLSD(), r);
        try
        {
            if (!r["paths"].isArray() || r["paths"].size() < 1 || r["paths"].size() > 20)
                throw std::runtime_error("Supply 1-20 exact paths");
            S32 max_bytes = bound(r, "max_bytes", 1024, 1, 4096);
            response["schema_version"] = 1;
            response["controls"] = LLSD::emptyArray();
            for (const LLSD& path : llsd::inArray(r["paths"]))
            {
                LLSD item;
                item["path"] = path.asString().substr(0, 2048);
                try { item = observation(exactView(path.asString()), r["include_values"].asBoolean(), max_bytes); item["path"] = path; }
                catch (const std::exception& e) { item["error"] = e.what(); }
                response["controls"].append(item);
            }
            response["same_event_loop_turn"] = true;
            response["instance_identity_verified"] = true;
        }
        catch (const std::exception& e) { response.error(e.what()); }
    }
    void getRows(const LLSD& r)
    {
        Response response(LLSD(), r);
        try
        {
            S32 offset = bound(r, "offset", 0, 0, 100000), limit = bound(r, "limit", 20, 1, 50);
            auto view = exactView(r["path"].asString());
            auto list = dynamic_cast<LLScrollListCtrl*>(view);
            if (!list || !view->isInVisibleChain()) throw std::runtime_error("A visible scroll list is required");
            response["schema_version"] = 1;
            response["rows"] = LLSD::emptyArray();
            response["total_rows"] = list->getItemCount();
            S32 end = llmin(list->getItemCount(), offset + limit), bytes = 0, index = offset;
            bool truncated = false;
            for (; index < end; ++index)
            {
                auto row = list->getItemByIndex(index);
                if (!row) throw std::runtime_error("Row unavailable");
                LLSD cells = LLSD::emptyArray();
                for (S32 col = 0; col < llmin(row->getNumColumns(), 8); ++col)
                {
                    auto cell = row->getColumn(col);
                    std::string text = cell ? cell->getValue().asString() : "";
                    if (text.size() > 1024 || bytes + text.size() > 32768) { truncated = true; break; }
                    bytes += (S32)text.size(); cells.append(text);
                }
                if (truncated) break;
                response["rows"].append(LLSD().with("index", index).with("cells", cells).with("columns_truncated", row->getNumColumns() > 8));
            }
            response["truncated"] = truncated || index < list->getItemCount();
            response["next_offset"] = index > offset && index < list->getItemCount() ? LLSD(index) : LLSD();
            response["evidence"] = "viewer_ui_rows";
            response["compile_verified"] = false;
        }
        catch (const std::exception& e) { response.error(e.what()); }
    }
};
}
void initFSMCPUI() { static FSMCPUI api; }
