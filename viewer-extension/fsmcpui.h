// SPDX-License-Identifier: MIT
#pragma once
#include <string>
void fsmcpStartLeap(const std::string& command);
void initFSMCPUI();
// Called immediately before a normal framebuffer swap; never forces rendering.
void fsmcpUICaptureFrame();
