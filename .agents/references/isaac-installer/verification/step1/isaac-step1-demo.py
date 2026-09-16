#!/usr/bin/python3
"""Retained synthetic native Sim/Lab CLI workflow; no actual workstation inputs."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import yaml

ROOT=Path('/workspaces/IsaacAutomator')
ENTRY=ROOT/'isaac-installer/bin/isaac-installer'
spec=importlib.util.spec_from_file_location('step1_boundary',Path(__file__).with_name('isaac-step1-runner.py'))
assert spec is not None and spec.loader is not None
boundary=importlib.util.module_from_spec(spec); spec.loader.exec_module(boundary)

def digest_tree(root):
    return {str(p.relative_to(root)): {'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
            'mode':stat.S_IMODE(p.stat().st_mode)} for p in sorted(root.rglob('*')) if p.is_file()}

def run(base):
    base=Path(base)
    os.environ.update(HOME=str(base),TMPDIR=str(base),PYTHONDONTWRITEBYTECODE='1')
    tempfile.tempdir=str(base); os.chdir(base); boundary.confine(base)
    inputs=base/'inputs'; reports=base/'reports'; reports.mkdir(mode=0o700)
    # The exclusive writer requires existing exclusion roots. Prepare an empty
    # synthetic user home before any CLI call, not an installed environment.
    target=base/'target-home'; target.mkdir(mode=0o700)
    workspace=inputs/'Documents/GitHub'; checkout=workspace/'BoredEngineer/IsaacLab'; git=checkout/'.git'
    git.mkdir(parents=True)
    commit='a'*40
    (git/'HEAD').write_text(commit+'\n')
    (git/'config').write_text('[remote "origin"]\nurl = https://github.com/example/IsaacLab.git\n')
    (checkout/'untracked-progress.txt').write_text('SYNTHETIC_UNTRACKED_PROGRESS_DO_NOT_CHANGE\n')
    (checkout/'README.md').write_text('Synthetic existing checkout; not a valid upstream revision.\n')
    metadata=inputs/'environment.json'
    metadata.write_text(json.dumps({'name':'isaaclab','manager':'conda','python':'3.12',
        'tools':[{'name':'synthetic-robot-helper','version':'1.2.3','source':None,'purpose':None}], 'notes':[]}))
    before=digest_tree(inputs)
    git_selection={'id':'synthetic-lab','root':str(checkout),'git_dir':str(git),'common_dir':str(git),
                   'ref_paths':[],'component':'lab'}
    runtime_selection={'id':'synthetic-env','path':str(metadata),'format':'environment-json',
                       'environment':'isaaclab','placement':'environment','runtime':'lab'}
    observation_args=['observe','--workspace-root',str(workspace),'--workspace-name','BoredEngineer',
                      '--git-source',json.dumps(git_selection),'--metadata-source',json.dumps(runtime_selection)]
    receipts=[]
    def cli(label,args,code=0):
        output=reports/(label+('.yaml' if label=='05-desired' else '.json'))
        cmd=['/bin/bash',str(ENTRY),*args,'--output',str(output)]
        result=subprocess.run(cmd,cwd=base,env={'PATH':'/usr/bin:/bin','HOME':str(base),'LANG':'C.UTF-8'},
                              capture_output=True,text=True,timeout=30)
        receipt={'step':label,'argv':cmd,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
        receipts.append(receipt); (reports/'commands.json').write_text(json.dumps(receipts,indent=2))
        assert result.returncode==code,(label,result.returncode,result.stdout,result.stderr)
        assert output.is_file(),(label,'missing artifact')
        assert stat.S_IMODE(output.stat().st_mode)==0o600
        assert json.loads(result.stdout)['status']=='written'
        return output
    observed=cli('01-observed',observation_args)
    observed_bundle=json.loads(observed.read_text())
    assert not observed_bundle['candidate']['apply_supported']
    assert all(f['state']!='accepted' for f in observed_bundle['candidate']['fields'])
    assert 'SYNTHETIC_UNTRACKED_PROGRESS_DO_NOT_CHANGE' not in observed.read_text()
    decisions=[{'field_id':f['id'],'decision':'accept'} for f in observed_bundle['candidate']['fields']
               if f['id'].startswith('workspace:')]
    decisions += [
        {'field_id':'components.selection','decision':'edit','value':['sim','lab']},
        {'field_id':'component:lab.source','decision':'accept'},
        {'field_id':'runtime:lab','decision':'accept'},
        {'field_id':'environment:synthetic-env','decision':'accept'},
        {'field_id':'component:sim.source','decision':'declare','value':{
            'mode':'standalone','version':'6.0.1','url':'https://example.org/synthetic-isaac-sim.zip',
            'sha256':hashlib.sha256(b'SYNTHETIC_ARCHIVE_PLACEHOLDER_NOT_DOWNLOADED').hexdigest()}},
        {'field_id':'runtime:kit','decision':'declare','value':{'manager':'bundled','environment':'kit'}},
        {'field_id':'component:sim.execution','decision':'declare','value':'native'},
        {'field_id':'component:lab.execution','decision':'declare','value':'native'},
    ]
    tool=next(f for f in observed_bundle['candidate']['fields'] if f['id']=='tool:synthetic-env:synthetic-robot-helper')
    decisions.append({'field_id':tool['id'],'decision':'edit','required':False,
        'value':{**tool['value'],'source':'pypi','purpose':'Synthetic robot calibration helper','location':None}})
    decision_file=reports/'02-decisions.json'; decision_file.write_text(json.dumps(decisions,indent=2)); decision_file.chmod(0o600)
    reviewed=cli('03-reviewed',['review-profile','--report',str(observed),'--decisions',str(decision_file)])
    rescanned=cli('04-rescanned',[*observation_args,'--previous-report',str(reviewed)])
    def chosen(path):
        return {f['id']:(f['value'],f['state']) for f in json.loads(path.read_text())['candidate']['fields'] if f['state']=='accepted'}
    assert chosen(reviewed)==chosen(rescanned),'rescan changed intent'
    desired=cli('05-desired',['export-profile','--report',str(rescanned),'--name','synthetic-native-sim-lab','--format','yaml'])
    full=cli('06-export-review',['export-profile','--report',str(rescanned),'--name','synthetic-native-sim-lab'])
    exported=json.loads(full.read_text()); profile=yaml.safe_load(desired.read_text())
    assert exported['complete'] and not profile['draft']
    assert {k for k,v in profile['components'].items() if v['enabled']}=={'sim','lab'}

    local=cli('07-local',['render-profile','--desired-profile',str(desired),'--target-home',str(target),'--adapter','local'])
    cloud=cli('08-ansible',['render-profile','--desired-profile',str(desired),'--target-home',str(target),'--adapter','ansible'])
    local_report=json.loads(local.read_text()); cloud_report=json.loads(cloud.read_text())
    for report in (local_report,cloud_report):
        assert report['render_supported'] and not report['execution_authorized'] and not report['apply_supported']
    local_artifact=local_report['artifact']; cloud_artifact=cloud_report['artifact']
    assert local_artifact['repositories']['isaaclab']['repo']=='https://github.com/example/IsaacLab.git'
    assert local_artifact['repositories']['isaaclab']['tag']==commit
    assert cloud_artifact['isaaclab_git_checkpoint']==commit
    assert local_artifact['simulation']['isaacsim']['version']=='6.0.1'
    assert local_artifact['runtimes']['lab']['packages']=='synthetic-robot-helper==1.2.3'
    assert cloud_artifact['profile_lab_packages']==['synthetic-robot-helper==1.2.3']
    planned=cli('09-dry-run',['install','--dry-run','--desired-profile',str(desired),'--target-home',str(target),'--json'],code=2)
    plan=json.loads(planned.read_text()); actions={r['id']:r for r in plan['actions']}
    assert not plan['execution_authorized']
    assert actions['component.lab']['target']==str(checkout)
    assert actions['component.sim']['target']==str(target/'IsaacSim')
    assert actions['component.lab']['status']=='unknown'
    evidence=cli('09b-target-metadata',['observe-targets','--desired-profile',str(desired),'--target-home',str(target)])
    bounded=cli('09c-dry-run-with-evidence',['install','--dry-run','--desired-profile',str(desired),
                 '--target-home',str(target),'--evidence',str(evidence),'--json'],code=2)
    bounded_plan=json.loads(bounded.read_text()); bounded_actions={r['id']:r for r in bounded_plan['actions']}
    assert bounded_actions['workspace.root']['status']=='satisfied'
    assert bounded_actions['workspace.group']['status']=='satisfied'
    assert bounded_actions['component.lab']['status']=='blocked'
    assert bounded_actions['component.sim']['status']=='would_change'
    assert not bounded_plan['execution_authorized']
    assert list(target.iterdir())==[]
    assert digest_tree(inputs)==before,'input contents or modes changed'
    # Real legacy parser consumes the rendered configuration, without sourcing
    # native modules or performing installation.
    sys.path.insert(0,str(ROOT/'isaac-installer/lib/core'))
    profile_parser=importlib.import_module('profile_parser')
    parsed=profile_parser.parse_profile_text(yaml.safe_dump(local_artifact))
    fields=parsed.decode('utf-8').split('\0')
    assert fields[-1]=='' and len(fields[:-1])%2==0
    parsed_values=dict(zip(fields[:-1:2],fields[1:-1:2]))
    assert parsed_values['CFG_REPOSITORIES_ISAACLAB_TAG']==commit
    assert parsed_values['CFG_SIMULATION_ISAACSIM_ENABLED']=='true'
    (reports/'10-legacy-parser.json').write_text(json.dumps(parsed_values,indent=2))
    result={'passed':True,'synthetic_only':True,'uid':os.getuid(),'enabled_components':['sim','lab'],
            'real_cli_steps':len(receipts),'observation_has_evidence':bool(observed_bundle['baseline']['observations']),
            'rescan_preserves_review':True,'export_complete':exported['complete'],'local_render_supported':True,
            'ansible_render_supported':True,'legacy_parser_consumed_artifact':True,
            'custom_tool_mapped_both_consumers':'synthetic-robot-helper==1.2.3',
            'dry_run_exit':2,'dry_run_reason':'Target state unobserved; concrete operations are not authorized.',
            'actions':[{k:r.get(k) for k in ('id','operation','target','status')} for r in plan['actions']],
            'fixture_metadata_statuses':{key:bounded_actions[key]['status'] for key in
                ('workspace.root','workspace.group','component.lab','component.sim')},
            'input_contents_and_modes_unchanged':True,'installation_targets_created':False,
            'fixture_home_precreated_and_remains_empty':True,
            'source_reachability':'NOT_CHECKED; example URL and hash are intentionally synthetic',
            'reports':str(reports)}
    (reports/'summary.json').write_text(json.dumps(result,indent=2)); print(json.dumps(result,indent=2))
    return 0

if __name__=='__main__':
    if sys.argv[1:2]==['--child']: sys.exit(run(sys.argv[2]))
    base=Path(tempfile.mkdtemp(prefix='isaac-step1-demo-'))
    if os.geteuid()==0: os.chown(base,65534,65534)
    print('DEMO_ROOT '+str(base),flush=True)
    proc=subprocess.run(['/usr/bin/python3','-B',__file__,'--child',str(base)],
                        env={'PATH':'/usr/bin:/bin','HOME':str(base),'LANG':'C.UTF-8'},cwd=base,
                        capture_output=True,text=True,timeout=180)
    (base/'execution.log').write_text(proc.stdout+proc.stderr)
    print(proc.stdout+proc.stderr); sys.exit(proc.returncode)
