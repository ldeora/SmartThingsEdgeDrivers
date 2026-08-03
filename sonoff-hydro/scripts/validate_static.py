#!/usr/bin/env python3
from pathlib import Path
import re, sys, yaml, json

ROOT=Path(__file__).resolve().parents[1]
INIT=(ROOT/'src/init.lua').read_text()
UTIL=(ROOT/'src/sonoff_utils.lua').read_text()
errors=[]

def require(cond,msg):
    if not cond: errors.append(msg)

def function_body(name):
    patterns=[rf'local function {re.escape(name)}\b',rf'{re.escape(name)}\s*=\s*function\b']
    starts=[m for pat in patterns for m in re.finditer(pat,INIT)]
    require(len(starts)==1,f'{name}: expected one definition, found {len(starts)}')
    if len(starts)!=1: return ''
    start=starts[0].start()
    nxt=re.search(r'\n(?:local function\s+\w+|\w+\s*=\s*function\b|function\s+\w+)',INIT[start+1:])
    end=start+1+nxt.start() if nxt else len(INIT)
    return INIT[start:end]

require('local DRIVER_VERSION = "1.4.0-alpha29"' in INIT,'version constant mismatch')
for profile in ['sonoff-hydro-one.yml','sonoff-hydro-one-lite.yml','sonoff-hydro-duo.yml']:
    data=yaml.safe_load((ROOT/'profiles'/profile).read_text())
    caps=[]
    for component in data.get('components',[]):
        caps += [c.get('id') for c in component.get('capabilities',[])]
    for cap in ['valve','switch','battery','refresh','healthCheck','firmwareUpdate','oceancircle09600.hydroTimedWatering']:
        require(cap in caps,f'{profile}: missing {cap}')
    prefs={p['name'] for p in data.get('preferences',[])}
    for pref in ['manualDuration','childLock','debugLogging','readPrivateOnRefresh']:
        require(pref in prefs,f'{profile}: missing preference {pref}')

for name,cmd in [('send_on','OnOff.server.commands.On'),('send_off','OnOff.server.commands.Off')]:
    body=function_body(name)
    require(cmd in body,f'{name}: standard command missing')
    require('ATTR_MANUAL_DEFAULT_SETTINGS' not in body and 'write_manual_default_duration' not in body and 'read_private_attribute' not in body,f'{name}: private 0x501D coupling detected')

body=function_body('send_timed_open')
require('OnOff.server.commands.On' in body,'timed watering: standard On missing')
require('call_with_delay' in body and 'send_off' in body,'timed watering: delayed Off missing')
require('ATTR_MANUAL_DEFAULT_SETTINGS' not in body and 'write_manual_default_duration' not in body and 'read_private_attribute' not in body,'timed watering: private 0x501D coupling detected')
require(INIT.find('OnOff.server.commands.On(device)',INIT.find('local function send_on')) < INIT.find('cancel_all_timed_sessions',INIT.find('local function send_on')),'send_on: standard On must be queued before bookkeeping')
require('capabilities.firmwareUpdate' in INIT,'firmwareUpdate not supported')
require('[Basic.attributes.SWBuildID.ID] = firmware_version_attr_handler' in INIT,'firmware handler not registered')
require('utils.build_explicit_uint8_array' in INIT,'explicit 0x501D serializer not used')
require('payload[2] = (target >> 8)' in INIT and 'payload[3] = target & 0xFF' in INIT and 'payload[4] = (target >> 8)' in INIT and 'payload[5] = target & 0xFF' in INIT,'0x501D dual-duration patch missing')
require('payload[11] = (target >> 8)' in INIT and 'payload[12] = target & 0xFF' in INIT,'0x501D full/DUO fail-safe patch missing')
require('if not is_lite_device(device)' in function_body('process_manual_sync_readback'),'0x501D fail-safe write must remain disabled for Lite')
require('manual_duration_user_configured' in INIT,'explicit manual-duration configuration marker missing')
require('MANUAL_SYNC_TIMEOUT_SECONDS' in INIT,'bounded 0x501D synchronization timeout missing')
require('source_kind == \"read_response\"' in INIT,'0x501D synchronization must advance only from a read response')
require('[zcl_global_commands.ReadAttributeResponse.ID] = private_cluster_read_response_handler' in INIT,'dedicated private read-response handler missing')
require('DUO_ABNORMAL_FROST_CH1' in INIT and 'DUO_ABNORMAL_HIGH_FLOW' in INIT,'corrected DUO abnormal mapping missing')
require('ATTR_UNIT_OF_WATER_FLOW' in UTIL and 'build_explicit_uint8_array' in UTIL,'updated utility support missing')

# Custom capability JSON must remain valid.
for path in (ROOT/'custom-capabilities').rglob('*.json'):
    try: json.loads(path.read_text())
    except Exception as e: errors.append(f'{path.relative_to(ROOT)}: invalid JSON: {e}')

if errors:
    print('Static validation FAILED:')
    for e in errors: print(' -',e)
    sys.exit(1)
print('Static validation passed.')
