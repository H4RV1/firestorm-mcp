"""Apply FSMCPAssets v1 to a separate Firestorm 7.2.4 checkout with FSMCPBuilder.

All anchors are checked before any writes. This script never builds, launches or
updates an installed viewer. Keep the generated patch with its source baseline.
"""
import argparse
from pathlib import Path


def apply(checkout, extension):
    viewer = checkout / 'indra/newview'
    edits = {
        'CMakeLists.txt': [('    fsmcpbuilder.cpp\n', '    fsmcpbuilder.cpp\n    fsmcpassets.cpp\n'),
                           ('    fsmcpbuilder.h\n', '    fsmcpbuilder.h\n    fsmcpassets.h\n')],
        'llappviewer.cpp': [('#include "fsmcpbuilder.h"', '#include "fsmcpbuilder.h"\n#include "fsmcpassets.h"'),
                            ('initFSMCPBuilder();', 'initFSMCPBuilder();\n    initFSMCPAssets();')],
        'llstartup.cpp': [('#include "llviewerprecompiledheaders.h"', '#include "llviewerprecompiledheaders.h"\n#include "fsmcpassets.h"'),
            ('LLSD response = LLLoginInstance::getInstance()->getResponse();\n\n    // <FS:Ansariel> OpenSim legacy economy support',
             'LLSD response = LLLoginInstance::getInstance()->getResponse();\n    fsmcpAssetsLoginBenefits(response["agent_id"].asUUID(), response["account_level_benefits"]["sound_upload_cost"]);\n\n    // <FS:Ansariel> OpenSim legacy economy support')],
        'llviewermessage.cpp': [('#include "llviewerprecompiledheaders.h"', '#include "llviewerprecompiledheaders.h"\n#include "fsmcpassets.h"'),
            ('void process_object_properties_family(LLMessageSystem *msg, void**user_data)\n{',
             'void process_object_properties_family(LLMessageSystem *msg, void**user_data)\n{\n    fsmcpAssetsProperties(msg);'),
            ('void process_chat_from_simulator(LLMessageSystem *msg, void **user_data)\n{',
             'void process_chat_from_simulator(LLMessageSystem *msg, void **user_data)\n{\n    fsmcpAssetsChat(msg);'),
            ('void process_script_dialog(LLMessageSystem* msg, void**)\n{',
             'void process_script_dialog(LLMessageSystem* msg, void**)\n{\n    fsmcpAssetsDialog(msg);'),
            ('        msg->newMessage("ScriptDialogReply");',
             '        fsmcpAssetsDialogAnswered(notification["payload"]["object_id"].asUUID(), notification["payload"]["chat_channel"].asInteger());\n        msg->newMessage("ScriptDialogReply");')],
    }
    pending = {}
    for name, replacements in edits.items():
        source = (viewer / name).read_text(encoding='utf-8')
        if 'fsmcpassets' in source.lower():
            raise ValueError('Already patched: ' + name)
        for before, after in replacements:
            if source.count(before) != 1:
                raise ValueError('Unexpected source anchor in ' + name + ': ' + before)
            source = source.replace(before, after)
        pending[viewer / name] = source
    for name in ('fsmcpassets.cpp', 'fsmcpassets.h', 'fsmcpassetpolicy.h', 'fsmcpsound.h'):
        target = viewer / name
        if target.exists():
            raise ValueError('Extension already exists: ' + str(target))
        pending[target] = (extension / name).read_text(encoding='utf-8')
    for target, source in pending.items():
        target.write_text(source, encoding='utf-8', newline='\n')
    return list(pending)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path)
    args = parser.parse_args()
    for path in apply(args.checkout.resolve(), Path(__file__).resolve().parents[1] / 'viewer-extension'):
        print(path)
