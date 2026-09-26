// SPDX-License-Identifier: MIT
// Experimental read-only LEAP extension. Compile/live verification is required.
#include "llviewerprecompiledheaders.h"
#include "fsmcpbuilder.h"
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
    FSMCPBuilder() : LLEventAPI("FSMCPBuilder", "Read-only builder observations, schema version 1")
    {
        add("getSelection", "Read current selected prims and selected texture-entry indices on [\"reply\"]",
            &FSMCPBuilder::getSelection, LLSD().with("reply", LLSD()));
        add("getLinkset", "Read viewer-cache link order for [\"object_id\"] on [\"reply\"]; completeness is unverified",
            &FSMCPBuilder::getLinkset, LLSD().with("object_id", LLSD()).with("reply", LLSD()));
        add("getFaces", "Read texture entries of [\"object_id\"] on [\"reply\"]; no asset contents or resolved PBR data",
            &FSMCPBuilder::getFaces, LLSD().with("object_id", LLSD()).with("reply", LLSD()));
    }

private:
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
        auto selection = LLSelectMgr::getInstance()->getSelection();
        for (auto iter = selection->begin(); iter != selection->end(); ++iter)
        {
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
}
