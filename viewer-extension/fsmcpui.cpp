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
#include "llviewerwindow.h"
#include "llwindow.h"
#include "llfocusmgr.h"
#include "llbutton.h"
#include "llcheckboxctrl.h"
#include "llimagepng.h"
#include "llrender.h"
#include "pipeline.h"
#include "lluuid.h"
#include "llleap.h"
#include "lleventtimer.h"
#include "llapp.h"
#include <cmath>
#include <chrono>
#include <functional>
#include <stdexcept>

namespace
{
using Clock = std::chrono::steady_clock;
struct Capture
{
    LLUUID id;
    std::string path;
    LLRect rect;
    LLHandle<LLView> view;
    S32 width = 0, height = 0, max_size = 1280;
    Clock::time_point expires;
    LLSD result;
    LLSD::Binary png;
    S32 offset = 0;
};
Capture capture;

LLSD context()
{
    LLSD value;
    value["schema_version"] = 1;
    value["app_has_focus"] = gFocusMgr.getAppHasFocus();
    value["window_visible"] = gViewerWindow->getWindow()->getVisible();
    value["window_minimized"] = gViewerWindow->getWindow()->getMinimized();
    value["render_active"] = gViewerWindow->getActive();
    value["width"] = gViewerWindow->getWindowWidthRaw();
    value["height"] = gViewerWindow->getWindowHeightRaw();
    value["ui_scale_x"] = gViewerWindow->getDisplayScale().mV[VX];
    value["ui_scale_y"] = gViewerWindow->getDisplayScale().mV[VY];
    value["desktop_input_used"] = false;
    value["focus_requested"] = false;
    return value;
}

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
        add("getContext", "Window/render state without activation or input.", &FSMCPUI::getContext, LLSD().with("reply", LLSD()));
        add("getScene", "Scoped structural UI map, <=128 controls, 1024 visits, 8 ms. No field values.",
            &FSMCPUI::getScene, LLSD().with("reply", LLSD()).with("under", LLSD()));
        add("requestCapture", "Request one scoped next-frame capture. Does not render, activate, restore or move the cursor. Expires in five seconds.",
            &FSMCPUI::requestCapture, LLSD().with("reply", LLSD()).with("path", LLSD()));
        add("captureResult", "Read frame metadata. Ready PNG uses captureChunk in <=8192-byte pieces; expires after 30 seconds.",
            &FSMCPUI::captureResult, LLSD().with("reply", LLSD()).with("capture_id", LLSD()));
        add("captureChunk", "Consume the next bounded PNG chunk at the exact byte offset. No retries or cached frame fallback.",
            &FSMCPUI::captureChunk, LLSD().with("reply", LLSD()).with("capture_id", LLSD()).with("offset", LLSD()));
    }
private:
    void getContext(const LLSD& r) { Response response(context(), r); }
    void getScene(const LLSD& r)
    {
        Response response(LLSD(), r);
        try
        {
            S32 limit = bound(r, "limit", 80, 1, 128), depth_limit = bound(r, "max_depth", 3, 0, 8);
            auto started = Clock::now();
            auto root = exactView(r["under"].asString());
            response["schema_version"] = 1; response["context"] = context();
            response["root"] = observation(root, false, 1);
            response["controls"] = LLSD::emptyArray();
            bool stopped = false, depth_limited = false;
            S32 visits = 0, bytes = 0;
            std::function<void(LLView*, S32)> visit = [&](LLView* view, S32 depth)
            {
                if (stopped) return;
                if (++visits > 1024 || Clock::now() - started > std::chrono::milliseconds(8)) { stopped = true; return; }
                if (!view->isInVisibleChain()) return;
                LLSD item = observation(view, false, 1);
                std::string path = item["path"].asString();
                if (path.size() > 2048 || bytes + path.size() > 65536 || response["controls"].size() >= limit) { stopped = true; return; }
                bytes += (S32)path.size();
                item["name"] = view->getName().size() <= 128 ? view->getName() : "[name exceeds byte limit]";
                item["depth"] = depth;
                item["role"] = dynamic_cast<LLButton*>(view) ? "button" : dynamic_cast<LLCheckBoxCtrl*>(view) ? "checkbox" : "view";
                response["controls"].append(item);
                if (depth == depth_limit) { depth_limited |= !view->getChildList()->empty(); return; }
                for (LLView* child : *view->getChildList()) { visit(child, depth + 1); if (stopped) break; }
            };
            visit(root, 0);
            response["truncated"] = stopped; response["depth_limited"] = depth_limited;
            response["visited"] = visits; response["values_included"] = false;
            response["evidence"] = "ui_structure_not_pixels";
        }
        catch (const std::exception& e) { response.error(e.what()); }
    }
    void requestCapture(const LLSD& r)
    {
        Response response(LLSD(), r);
        try
        {
            response["schema_version"] = 1;
            if (capture.id.notNull() && Clock::now() < capture.expires) throw std::runtime_error("A capture is pending or awaiting consumption");
            auto state = context();
            if (!state["window_visible"].asBoolean() || state["window_minimized"].asBoolean() || !state["render_active"].asBoolean())
            {
                response["state"] = "unavailable"; response["reason"] = "render_suspended"; response["context"] = state; return;
            }
            auto view = exactView(r["path"].asString());
            if (!view->isInVisibleChain()) throw std::runtime_error("Capture target is hidden");
            S32 width = state["width"].asInteger(), height = state["height"].asInteger();
            LLRect scaled = view->calcScreenRect();
            const auto& scale = gViewerWindow->getDisplayScale();
            LLRect rect(llclamp((S32)std::floor(scaled.mLeft * scale.mV[VX]), 0, width),
                        llclamp((S32)std::ceil(scaled.mTop * scale.mV[VY]), 0, height),
                        llclamp((S32)std::ceil(scaled.mRight * scale.mV[VX]), 0, width),
                        llclamp((S32)std::floor(scaled.mBottom * scale.mV[VY]), 0, height));
            if (rect.getWidth() < 1 || rect.getHeight() < 1 || (S64)rect.getWidth() * rect.getHeight() > 4194304)
                throw std::runtime_error("Capture crop must contain 1-4194304 pixels; choose a smaller panel");
            S32 max_size = bound(r, "max_size", 1280, 64, 1600);
            capture = Capture(); capture.id.generate(); capture.path = r["path"].asString(); capture.rect = rect;
            capture.view = view->getHandle(); capture.width = width; capture.height = height; capture.max_size = max_size;
            capture.expires = Clock::now() + std::chrono::seconds(5);
            capture.result = LLSD().with("state", "pending");
            response["capture_id"] = capture.id; response["state"] = "pending";
            response["context"] = state;
        }
        catch (const std::exception& e) { response.error(e.what()); }
    }
    void captureResult(const LLSD& r)
    {
        Response response(LLSD(), r);
        response["schema_version"] = 1;
        if (capture.id.isNull() || LLUUID(r["capture_id"].asString()) != capture.id || Clock::now() >= capture.expires)
        { response["state"] = "unavailable"; response["reason"] = "expired_or_unknown"; return; }
        response["capture_id"] = capture.id;
        response["result"] = capture.result;
        response["state"] = capture.result["state"];
        if (capture.result["state"].asString() == "unavailable") capture = Capture();
    }
    void captureChunk(const LLSD& r)
    {
        Response response(LLSD(), r);
        response["schema_version"] = 1;
        if (capture.id.isNull() || LLUUID(r["capture_id"].asString()) != capture.id ||
            Clock::now() >= capture.expires || capture.result["state"].asString() != "ready")
        { response.error("Capture expired or unavailable"); return; }
        if (!r["offset"].isInteger() || r["offset"].asInteger() != capture.offset)
        { response.error("Capture offset mismatch; do not replay a consumed chunk"); return; }
        S32 end = llmin(capture.offset + 8192, (S32)capture.png.size());
        response["capture_id"] = capture.id;
        response["offset"] = capture.offset;
        response["next_offset"] = end;
        response["data"] = LLSD::Binary(capture.png.begin() + capture.offset, capture.png.begin() + end);
        response["done"] = end == (S32)capture.png.size();
        capture.offset = end;
        if (response["done"].asBoolean()) capture = Capture();
    }
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

void fsmcpUICaptureFrame()
{
    if (capture.id.isNull()) return;
    if (Clock::now() >= capture.expires) { capture = Capture(); return; }
    if (capture.result["state"].asString() != "pending") return;
    try
    {
        auto view = capture.view.get();
        if (!view || !view->isInVisibleChain() || exactView(capture.path) != view ||
            gViewerWindow->getWindowWidthRaw() != capture.width || gViewerWindow->getWindowHeightRaw() != capture.height)
            throw std::runtime_error("capture_target_changed");
        LLRect scaled = view->calcScreenRect();
        const auto& scale = gViewerWindow->getDisplayScale();
        LLRect rect(llclamp((S32)std::floor(scaled.mLeft * scale.mV[VX]), 0, capture.width),
                    llclamp((S32)std::ceil(scaled.mTop * scale.mV[VY]), 0, capture.height),
                    llclamp((S32)std::ceil(scaled.mRight * scale.mV[VX]), 0, capture.width),
                    llclamp((S32)std::floor(scaled.mBottom * scale.mV[VY]), 0, capture.height));
        if (rect != capture.rect) throw std::runtime_error("capture_geometry_changed");
        if (!gPipeline.hasRenderDebugFeatureMask(LLPipeline::RENDER_DEBUG_FEATURE_UI)) throw std::runtime_error("ui_rendering_disabled");
        GLint framebuffer = 0, pack_buffer = 0;
        glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &framebuffer);
        glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING, &pack_buffer);
        if (framebuffer || pack_buffer) throw std::runtime_error("unsupported_readback_state");
        LLPointer<LLImageRaw> raw = new LLImageRaw(rect.getWidth(), rect.getHeight(), 3);
        if (!raw->getData()) throw std::runtime_error("capture_allocation_failed");
        GLint read_buffer, alignment, row_length, skip_rows, skip_pixels;
        glGetIntegerv(GL_READ_BUFFER, &read_buffer); glGetIntegerv(GL_PACK_ALIGNMENT, &alignment);
        glGetIntegerv(GL_PACK_ROW_LENGTH, &row_length); glGetIntegerv(GL_PACK_SKIP_ROWS, &skip_rows);
        glGetIntegerv(GL_PACK_SKIP_PIXELS, &skip_pixels);
        gGL.flush(); glReadBuffer(GL_BACK);
        glPixelStorei(GL_PACK_ALIGNMENT, 1); glPixelStorei(GL_PACK_ROW_LENGTH, 0);
        glPixelStorei(GL_PACK_SKIP_ROWS, 0); glPixelStorei(GL_PACK_SKIP_PIXELS, 0);
        glReadPixels(rect.mLeft, rect.mBottom, rect.getWidth(), rect.getHeight(), GL_RGB, GL_UNSIGNED_BYTE, raw->getData());
        GLenum error = glGetError();
        glReadBuffer(read_buffer); glPixelStorei(GL_PACK_ALIGNMENT, alignment); glPixelStorei(GL_PACK_ROW_LENGTH, row_length);
        glPixelStorei(GL_PACK_SKIP_ROWS, skip_rows); glPixelStorei(GL_PACK_SKIP_PIXELS, skip_pixels);
        if (error != GL_NO_ERROR) throw std::runtime_error("capture_gl_error");
        F64 factor = llmin(1.0, (F64)capture.max_size / llmax(rect.getWidth(), rect.getHeight()));
        if (factor < 1.0 && !raw->scale(llmax(1, (S32)(rect.getWidth() * factor)), llmax(1, (S32)(rect.getHeight() * factor))))
            throw std::runtime_error("capture_scale_failed");
        LLPointer<LLImagePNG> png = new LLImagePNG;
        if (!png->encode(raw, 0.0f) || png->getDataSize() > 4194304) throw std::runtime_error("capture_encoding_limit");
        capture.png.assign(png->getData(), png->getData() + png->getDataSize());
        capture.result = LLSD().with("state", "ready").with("png_transfer", "chunks_v1").with("png_size", png->getDataSize())
            .with("width", raw->getWidth()).with("height", raw->getHeight()).with("context", context())
            .with("path", capture.path).with("evidence", "normal_render_frame_after_request")
            .with("occlusion", "viewer_panels_may_overlap_target").with("captured_at", LLDate::now());
    }
    catch (const std::exception& e) { capture.result = LLSD().with("state", "unavailable").with("reason", e.what()); }
    capture.expires = Clock::now() + std::chrono::seconds(30);
}

namespace
{
// Only the configured MCP helper is supervised, never arbitrary viewer plugins.
class MCPLeapWatch final : public LLEventTimer
{
    std::string command;
    LLLeap::weak_t child;
    U32 retries = 0;
    U32 ticks = 0;
public:
    MCPLeapWatch(const std::string& value, LLLeap* initial) : LLEventTimer(2.f), command(value)
    { if (initial) child = initial->getWeak(); }
    bool tick() override
    {
        if (LLApp::isExiting()) return true;
        if (!child.expired()) { ticks = 0; return false; }
        if (retries >= 3) { LL_WARNS("FSMCP") << "MCP helper restart limit reached" << LL_ENDL; return true; }
        if (++ticks < (1U << retries)) return false;
        ticks = 0; ++retries;
        auto next = LLLeap::create("MCP recovery", command, false);
        if (next) child = next->getWeak();
        LL_INFOS("FSMCP") << "MCP helper restart attempt " << retries << "; no actions replayed" << LL_ENDL;
        return false;
    }
};
}

void fsmcpStartLeap(const std::string& command)
{
    auto child = LLLeap::create("", command, false);
    if (command.find("firestorm_mcp/leap_entry.py") != std::string::npos ||
        command.find("firestorm_mcp\\leap_entry.py") != std::string::npos)
        new MCPLeapWatch(command, child);
}
