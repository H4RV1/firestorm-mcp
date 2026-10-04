// SPDX-License-Identifier: MIT
// Synthetic dependencies for methods extracted from the actual viewer checkout.
#include <cassert>
#include <iostream>
#include <sstream>
#include <string>
#define LL_DARWIN 0
#define STRINGIZE(value) ([&]() { std::ostringstream out; out << value; return out.str(); }())
using KEY = unsigned char;
using MASK = unsigned int;
constexpr KEY KEY_RETURN = 13, KEY_DELETE = 127, KEY_BACKSPACE = 8;
constexpr MASK MASK_NONE = 0;
struct LLSD {
    std::string value;
    LLSD() = default;
    LLSD(const char* text): value(text) {}
    std::string asString() const { return value; }
    operator std::string() const { return value; }
    bool has(const char*) const { return true; }
    LLSD operator[](const char*) const { return *this; }
};
struct LLView;
struct Handle { LLView* view; LLView* get() const; };
struct LLView {
    bool available = true, alive = true;
    virtual ~LLView() = default;
    bool isAvailable() { return available; }
    LLSD getInfo() { return {}; }
    Handle getHandle() { return {this}; }
};
LLView* Handle::get() const { return view->alive ? view : nullptr; }
struct LLFolderView {};
struct LLInventoryModel {} gInventory;
int inventory_actions = 0, downs = 0, ups = 0, unicode_chars = 0;
std::string last_error;
struct LLInventoryAction {
    static void doToSelected(LLInventoryModel*, LLFolderView* root, const std::string&) {
        assert(root); // An unguarded original panel reproduces the failing call.
        ++inventory_actions;
    }
};
struct LLViewerObject { bool permModify() { return true; } };
struct ObjectList { LLViewerObject* findObject(int) { return nullptr; } } gObjectList;
struct LLNotificationsUtil { static void add(const char*) {} };
struct LLPanelObjectInventory: LLView {
    LLFolderView* mFolders = nullptr;
    int mTaskUUID = 0;
    LLFolderView* getRootFolder() { return mFolders; }
    bool isSelectionRemovable() { return mFolders != nullptr; }
    void doToSelected(const LLSD&);
    bool handleKeyHere(KEY, MASK);
};
LLView* resolved_view = nullptr;
struct LLUI {
    static LLUI* getInstance() { static LLUI ui; return &ui; }
    LLView* getRootView() { return nullptr; }
    LLView* resolvePath(LLView*, const std::string&) { return resolved_view; }
};
struct Focus {
    LLView* focused = nullptr;
    bool reject = false, clear_inventory = false, hide = false, destroy = false;
    void setKeyboardFocus(LLView* view) {
        if (!reject) focused = view;
        if (clear_inventory) dynamic_cast<LLPanelObjectInventory*>(view)->mFolders = nullptr;
        if (hide) view->available = false;
        if (destroy) view->alive = false;
    }
    LLView* getKeyboardFocus() { return focused; }
} gFocusMgr;
struct ViewerInput { void handleKey(KEY, MASK, bool) { ++downs; } } gViewerInput;
struct Window { void handleUnicodeChar(KEY, MASK) { ++unicode_chars; } } window;
struct Keyboard { void handleTranslatedKeyUp(KEY, MASK) { ++ups; } } keyboard;
struct Response {
    Response(const LLSD&, const LLSD&) {}
    void setResponse(const LLSD&) {}
    void error(const std::string& message) { last_error = message; }
};
struct LLWindowListener {
    Window* mWindow = &window;
    Keyboard* mKbGetter() { return &keyboard; }
    KEY getKEY(const LLSD&) { return KEY_RETURN; }
    MASK getMask(const LLSD&) { return MASK_NONE; }
    void keyDown(const LLSD&);
    void keyUp(const LLSD&);
};

// GENERATED_METHODS

int main() {
    LLPanelObjectInventory panel;
    panel.doToSelected(LLSD("task_open"));
    panel.doToSelected(LLSD("delete"));
    panel.doToSelected(LLSD("rename"));
    assert(!panel.handleKeyHere(KEY_RETURN, MASK_NONE));
    assert(!panel.handleKeyHere(KEY_DELETE, MASK_NONE));
    assert(inventory_actions == 0);
    LLFolderView folder;
    panel.mFolders = &folder;
    assert(panel.handleKeyHere(KEY_RETURN, MASK_NONE));
    assert(inventory_actions == 1);
    assert(!panel.handleKeyHere(KEY_RETURN, 1));
    assert(inventory_actions == 1);
    panel.mFolders = nullptr; // selection refresh between inspection and action
    assert(!panel.handleKeyHere(KEY_RETURN, MASK_NONE));
    assert(inventory_actions == 1);

    LLWindowListener listener;
    LLSD event("/synthetic/contents");
    resolved_view = &panel;
    for (int mode = 0; mode < 6; ++mode) {
        // cleared tree, hidden target, rejected focus, focus clearing the tree,
        // focus hiding the target, and target destruction during focus.
        panel.mFolders = mode == 0 ? nullptr : &folder;
        panel.available = mode != 1;
        panel.alive = true;
        gFocusMgr = {};
        gFocusMgr.reject = mode == 2;
        gFocusMgr.clear_inventory = mode == 3;
        gFocusMgr.hide = mode == 4;
        gFocusMgr.destroy = mode == 5;
        last_error.clear();
        listener.keyDown(event);
        assert(!last_error.empty());
        assert(downs == 0 && unicode_chars == 0);
        last_error.clear();
        listener.keyUp(event);
        assert(!last_error.empty());
        assert(ups == 0);
    }
    panel.mFolders = &folder;
    panel.available = panel.alive = true;
    gFocusMgr = {};
    last_error.clear();
    listener.keyDown(event);
    listener.keyUp(event);
    assert(last_error.empty());
    assert(downs == 1 && ups == 1 && unicode_chars == 1);
    // Ordinary controls retain their targeted input behavior.
    LLView ordinary;
    resolved_view = &ordinary;
    listener.keyDown(event);
    listener.keyUp(event);
    assert(downs == 2 && ups == 2);
    resolved_view = nullptr;
    listener.keyDown(event);
    assert(!last_error.empty() && downs == 2);
    std::cout << "Actual inventory/key methods passed isolated crash regressions.\n";
}
