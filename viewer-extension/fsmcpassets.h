// SPDX-License-Identifier: MIT
#pragma once
class LLMessageSystem;
class LLUUID;
class LLSD;
void initFSMCPAssets();
void fsmcpAssetsProperties(LLMessageSystem* message);
void fsmcpAssetsChat(LLMessageSystem* message);
void fsmcpAssetsDialog(LLMessageSystem* message);
void fsmcpAssetsDialogAnswered(const LLUUID& object, int channel);
void fsmcpAssetsLoginBenefits(const LLUUID& avatar, const LLSD& soundCost);
