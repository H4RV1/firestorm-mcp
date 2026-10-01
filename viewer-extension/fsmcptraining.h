// SPDX-License-Identifier: MIT
#pragma once
#include "llfloater.h"
class LLMultiGesture;
class FSMCPTrainingFloater final : public LLFloater
{
public:
    explicit FSMCPTrainingFloater(const LLSD& key) : LLFloater(key) {}
    bool postBuild() override;
    void onOpen(const LLSD&) override;
    void draw() override;
private:
    void refreshGestures();
};
void initFSMCPTraining();
void renderFSMCPTraining();
void observeFSMCPTrainingGesture(const LLMultiGesture* gesture);
