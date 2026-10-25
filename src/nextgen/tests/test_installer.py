"""Offline installer/import cases; no packages, real units or live services."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src.nextgen.configuration import ConfigurationStore
from src.nextgen.install_support import prepare, units
from src.nextgen.secrets import SecretStore
from src.nextgen.storage.sqlite import connect

ROOT=Path(__file__).resolve().parents[3]


def load(name,path):
    loader=importlib.machinery.SourceFileLoader(name,str(path));spec=importlib.util.spec_from_loader(name,loader)
    module=importlib.util.module_from_spec(spec);loader.exec_module(module);return module


installer=load('nextgen_test_installer',ROOT/'bin/anime-discovery-install')
class InstallerSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config=self.root/'config';self.config.mkdir()
        self.database=self.root/'nextgen.sqlite'

    def test_fresh_setup_and_repeated_upgrade_preserve_values_and_keys(self):
        result=prepare(self.config,self.database,{'worker':{'concurrency':2}}, {'webhook_token':'w'*43})
        self.assertTrue(result['local_ready']);store=ConfigurationStore(self.config)
        before=(self.config/'secrets.json').read_bytes();settings=(self.config/'settings.json').read_bytes()
        prepare(self.config,self.root/'ignored.sqlite',{'worker':{'concurrency':9}},{'webhook_token':'r'*43})
        self.assertEqual((self.config/'secrets.json').read_bytes(),before)
        self.assertEqual((self.config/'settings.json').read_bytes(),settings)
        self.assertEqual(store.read().value('worker.concurrency'),2);self.assertFalse((self.root/'ignored.sqlite').exists())

    def test_prepared_setup_keeps_webhook_without_management_token(self):
        ConfigurationStore(self.config).initialize({'storage':{'database_path':str(self.database)}})
        SecretStore(self.config).initialize(webhook_token='w'*43)
        prepare(self.config,self.database,{}, {})
        keys=SecretStore(self.config).access_credentials()
        self.assertEqual(keys.webhook_token,'w'*43);self.assertFalse(keys.management_token)
        self.assertFalse((self.config/'management-password.json').exists())

    def test_upgrade_preserves_existing_administrator_password(self):
        from src.nextgen.api.password_store import PasswordStore
        prepare(self.config,self.database,{}, {})
        passwords=PasswordStore(self.config)
        passwords.replace('keep this administrator password',expected_revision=0)
        before=(self.config/'management-password.json').read_bytes()
        prepare(self.config,self.database,{}, {})
        self.assertEqual((self.config/'management-password.json').read_bytes(),before)
        self.assertTrue(passwords.verify('keep this administrator password')[1])

    def test_existing_legacy_database_is_not_upgraded(self):
        import sqlite3
        db=sqlite3.connect(self.database);db.execute('CREATE TABLE old_data(value TEXT)');db.execute("INSERT INTO old_data VALUES('preserve')");db.commit();db.close()
        with self.assertRaises(Exception):prepare(self.config,self.database,{}, {})
        db=sqlite3.connect(self.database)
        try:self.assertEqual(db.execute('SELECT * FROM old_data').fetchall(),[('preserve',)])
        finally:db.close()

    def test_units_use_real_paths_loopback_port_and_media_mounts(self):
        from src.nextgen.configuration_schema import ConfigurationSnapshot
        snapshot=ConfigurationSnapshot(1,{'api':{'port':8877},'storage':{'download_root':'/mnt/downloads','trial_root':'/mnt/staging','keep_root':'/mnt/Anime Library'}})
        rendered=units(snapshot,'/opt/anime-discovery',str(self.config),str(self.root),'anime-discovery',None)
        self.assertIn('http://127.0.0.1:8877',rendered['anime-discovery-api.service'])
        self.assertIn('/opt/anime-discovery/current/.venv/bin/python',rendered['anime-discovery-api.service'])
        self.assertIn('RequiresMountsFor=',rendered['anime-discovery-worker.service'])
        self.assertIn('"/mnt/Anime Library"',rendered['anime-discovery-worker.service'])
        self.assertNotIn('/mnt/Anime Library',rendered['anime-discovery-api.service'])
        for name in ('anime-discovery-api.service','anime-discovery-worker.service'):
            self.assertIn('Type=notify',rendered[name])
            self.assertIn('WatchdogSec=60s',rendered[name])
        self.assertIn('BindsTo=anime-discovery-api.service',rendered['anime-discovery-worker.service'])
        self.assertIn('RuntimeDirectoryMode=0700',rendered['anime-discovery-api.service'])
        self.assertIn('ANIME_DISCOVERY_ADMIN_SOCKET=',rendered['anime-discovery-api.service'])

    def test_rendered_units_pass_systemd_parser(self):
        import shutil
        import sys
        from src.nextgen.configuration_schema import ConfigurationSnapshot
        if shutil.which('systemd-analyze') is None:self.skipTest('systemd-analyze unavailable')
        executable=self.root/'current/.venv/bin/python'
        executable.parent.mkdir(parents=True)
        executable.symlink_to(sys.executable)
        rendered=units(ConfigurationSnapshot(1,{}),self.root,self.config,self.root,'anime-discovery',None)
        paths=[]
        for name,body in rendered.items():
            path=self.root/name
            path.write_text(body)
            paths.append(str(path))
        result=subprocess.run(['systemd-analyze','verify',*paths],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_plan_is_read_only_noninteractive_and_honors_existing_database(self):
        ConfigurationStore(self.config).initialize({'storage':{'database_path':str(self.database)}})
        output=io.StringIO()
        with patch.object(installer,'saved_defaults',return_value={}),patch.object(installer,'apply',side_effect=AssertionError()),contextlib.redirect_stdout(output):
            status=installer.main(['--plan','--json','--config-dir',str(self.config),'--database',str(self.root/'ignored.sqlite')])
        self.assertEqual(status,0);result=json.loads(output.getvalue())
        self.assertFalse(result['changes_made']);self.assertEqual(result['database'],str(self.database))
        self.assertFalse(self.database.exists())

    def test_default_completion_is_readable_and_json_is_opt_in(self):
        result={'installed':True,'started_services':[]}
        defaults={'config_dir':str(self.config),'root':str(self.root/'app')}
        for flags in (['--yes'],['--yes','--json']):
            output=io.StringIO()
            with patch.object(installer,'saved_defaults',return_value=defaults), \
                 patch.object(installer,'apply',return_value=result),contextlib.redirect_stdout(output):
                self.assertEqual(installer.main(flags),0)
            if '--json' in flags:self.assertEqual(json.loads(output.getvalue()),result)
            else:
                self.assertIn('installation completed successfully',output.getvalue())
                self.assertIn('No services were started.',output.getvalue())
                self.assertIn('systemctl start anime-discovery-api.service',output.getvalue())
                self.assertNotIn('"installed"',output.getvalue())

    def test_yes_never_prompts_and_interactive_mode_asks_before_changes(self):
        defaults={'root':str(self.root/'app'),'config_dir':str(self.root/'native'),
            'state_dir':str(self.root/'state'),'unit_dir':str(self.root/'units')}
        with patch.object(installer,'saved_defaults',return_value=defaults), \
             patch.object(installer,'apply',return_value={'installed':True}) as apply, \
             patch('builtins.input',side_effect=AssertionError('unattended prompt')), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(['--yes']),0);apply.assert_called_once()
        with patch.object(installer,'saved_defaults',return_value=defaults), \
             patch.object(installer,'apply',return_value={'installed':True}) as apply, \
             patch('builtins.input',side_effect=['','','','','no']) as ask, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main([]),0);apply.assert_not_called();self.assertEqual(ask.call_count,5)

    def test_shell_metacharacters_and_invalid_revision_are_refused(self):
        for argv in [['--plan','--root','/opt/$(touch bad)'],['--plan','--revision','HEAD'],['--plan','--source','https://token@example.com/repo.git']]:
            with patch.object(installer,'saved_defaults',return_value={}),contextlib.redirect_stderr(io.StringIO()):self.assertEqual(installer.main(argv),1)


class InstallerOrchestrationTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.namespace=SimpleNamespace
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.root=self.folder/'app';self.state=self.folder/'state'
        self.config=self.state/'config';self.unitdir=self.folder/'units';self.command=self.folder/'bin'/'install'
        self.events=[]
        with patch.object(installer,'saved_defaults',return_value={}):
            self.args=installer.parser().parse_args(['--yes','--source-dir',str(self.folder/'source'),'--root',str(self.root),
                '--state-dir',str(self.state),'--config-dir',str(self.config),'--unit-dir',str(self.unitdir),
                '--destination',str(self.command),'--start','none'])
            self.options=installer.resolve(self.args)

    def candidate(self,source,release,revision,execute):
        for name in ['src/nextgen/__main__.py','src/nextgen/install_support.py','bin/anime-discovery-install','bin/adm']:
            path=release/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# test candidate')
        return 'a'*40

    def execute(self,args,**kwargs):
        args=[str(a) for a in args];self.events.append(args)
        if args[:2]==['systemctl','show']:return subprocess.CompletedProcess(args,0,'not-found\n','')
        if args[:2]==['systemctl','is-active']:return subprocess.CompletedProcess(args,3,'','')
        return subprocess.CompletedProcess(args,0,'','')

    def service(self,release,options,command,payload,execute):
        self.events.append(['native',command])
        if command=='render':return {'anime-discovery-api.service':'[Unit]\nDescription=Test\n'}
        return {'local_ready':True}

    @contextlib.contextmanager
    def patches(self,service=None):
        account=self.namespace(pw_uid=1001,pw_gid=1001)
        with patch.object(installer.os,'geteuid',return_value=0),patch.object(installer.os,'chown'), \
             patch.object(installer.pwd,'getpwnam',return_value=account), \
             patch.object(installer.grp,'getgrnam',return_value=self.namespace(gr_gid=1001)), \
             patch.object(installer.shutil,'which',return_value='/tool'), \
             patch.object(installer,'extract_checkout',side_effect=self.candidate), \
             patch.object(installer,'service_call',side_effect=service or self.service):yield

    def test_fresh_install_handles_absent_units_and_installs_stable_command(self):
        with self.patches():result=installer.apply(self.options,self.args,self.execute)
        self.assertTrue(result['installed']);self.assertEqual(result['started_services'],[])
        self.assertTrue((self.root/'current').is_symlink());self.assertTrue(self.command.is_file())
        self.assertEqual(self.command.stat().st_mode&0o777,0o755)
        self.assertTrue(Path(str(self.command)+'.json').is_file())
        adm=self.command.parent/'adm'
        self.assertEqual(adm.stat().st_mode&0o777,0o755)
        self.assertIn(str(self.root/'current/bin/adm'),adm.read_text())
        self.assertIn('"$@"',adm.read_text())
        self.assertFalse(any(event[:2]==['systemctl','stop'] for event in self.events))
        self.assertIn(['native','prepare'],self.events);self.assertIn(['native','render'],self.events)
        self.assertFalse(any('apt-get' in event for event in self.events))

    def test_automated_password_is_sent_through_adm_stdin_only(self):
        password=self.folder/'password'
        password.write_text('automation password for testing\n')
        self.args.admin_password_file=password
        self.args.start='api'
        def execute(args,**kwargs):
            if '--password-stdin' in args:
                self.assertEqual(kwargs['input'],'automation password for testing\n')
                self.assertIn('--if-unset',args)
                self.assertNotIn('automation password for testing',args)
            result=self.execute(args,**kwargs)
            if args[:3]==['systemctl','is-active','--quiet']:
                return subprocess.CompletedProcess(args,0,'','')
            return result
        with self.patches():installer.apply(self.options,self.args,execute)
        self.assertTrue(any('--password-stdin' in event for event in self.events))

    def test_failed_native_setup_keeps_previous_release_and_units(self):
        old=self.root/'releases'/'old';old.mkdir(parents=True);(self.root/'current').symlink_to(old)
        self.unitdir.mkdir();unit=self.unitdir/'anime-discovery-api.service';unit.write_text('old unit')
        def failing(*args):raise RuntimeError('simulated setup failure')
        with self.patches(failing),self.assertRaises(RuntimeError):installer.apply(self.options,self.args,self.execute)
        self.assertEqual((self.root/'current').resolve(),old);self.assertEqual(unit.read_text(),'old unit')
        self.assertFalse(self.command.exists())
        self.assertFalse(any(event[:2]==['systemctl','start'] for event in self.events))

    def test_malicious_archive_is_refused_without_extracting_outside_release(self):
        import tarfile
        release=self.folder/'release';release.mkdir()
        def execute(args,**kwargs):
            if 'archive' in args:
                archive=Path(next(a.split('=',1)[1] for a in args if str(a).startswith('--output=')))
                with tarfile.open(archive,'w') as stream:
                    info=tarfile.TarInfo('../outside');info.size=1;stream.addfile(info,io.BytesIO(b'x'))
            return subprocess.CompletedProcess(args,0,'a'*40,'')
        with self.assertRaises(ValueError):installer.extract_checkout(self.folder/'source',release,None,execute)
        self.assertFalse((self.folder/'outside').exists())
