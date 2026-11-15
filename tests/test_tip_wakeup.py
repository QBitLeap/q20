"""No sleeps: exercise idle cost, prompt catch-up, reorg and outage scheduling."""
from copy import deepcopy
from unittest.mock import Mock,patch
from q20.messages import Incomplete
from test_runtime import RuntimeTests
from test_index import point,transaction,record

class ScriptedStop:
    def __init__(self,actions):self.actions=iter(actions);self.stopped=False;self.delays=[]
    def wait(self,seconds):
        self.delays.append(seconds)
        action=next(self.actions,True)
        if callable(action):action();return False
        self.stopped=bool(action);return self.stopped
    def is_set(self):return self.stopped

class TipWakeup(RuntimeTests):
    def probe_core(self):
        original=self.core.call
        def call(method,params):
            if method=='getblockchaininfo':
                self.core.calls.append((method,params));return {**self.core.identity(self.rules),'bestblockhash':self.core.blocks[-1]['hash']}
            return original(method,params)
        self.core.call=call
    def test_idle_probes_are_one_rpc_with_zero_sql_or_block_reads(self):
        self.runtime.sweep(self.index);tip=self.index.tip;self.probe_core();self.core.calls.clear();trace=[];self.index.db.set_trace_callback(trace.append);changes=self.index.db.total_changes
        self.runtime.stop=ScriptedStop([False,False,True]);self.runtime.wait_for_tip_change(tip)
        self.assertEqual(self.core.calls,[('getblockchaininfo',[])]*2);self.assertEqual(trace,[]);self.assertEqual(self.index.db.total_changes,changes);self.assertEqual(self.runtime.stop.delays,[20,20,20]);self.assertTrue(self.runtime.checkpoint()['observedSynchronized'])
    def test_new_tip_invalidates_status_then_only_new_block_is_fetched(self):
        self.runtime.sweep(self.index);tip=self.index.tip;self.probe_core();self.core.calls.clear();new={'height':1,'hash':point(501),'previousblockhash':tip[1],'tx':[transaction(2,record(tick='FAST'))]}
        self.runtime.stop=ScriptedStop([lambda:self.core.blocks.append(new)]);self.runtime.wait_for_tip_change(tip)
        pending=self.runtime.checkpoint();self.assertFalse(pending['observedSynchronized']);self.assertEqual(pending['indexHeight'],0);self.assertEqual(pending['indexHash'],tip[1]);self.assertFalse(any(m=='getblock' for m,_ in self.core.calls))
        state=self.runtime.sweep(self.index);self.assertTrue(state['observedSynchronized']);self.assertEqual(self.index.tip,(1,point(501)));self.assertEqual([args for method,args in self.core.calls if method=='getblock'],[[point(501),3]])
    def test_same_height_reorg_wakes_and_replays_without_trusting_height_only(self):
        block={'height':1,'hash':point(500),'previousblockhash':self.core.blocks[0]['hash'],'tx':[transaction(2,record(tick='OTHR'))]};self.core.blocks.append(block);self.runtime.sweep(self.index);tip=self.index.tip;self.probe_core()
        self.runtime.stop=ScriptedStop([lambda:self.core.blocks.__setitem__(1,{**block,'hash':point(501),'tx':[transaction(3)]})]);self.runtime.wait_for_tip_change(tip);self.assertFalse(self.runtime.checkpoint()['observedSynchronized']);self.runtime.sweep(self.index);self.assertIsNone(self.index.get('token','OTHR'));self.assertEqual(self.index.tip,(1,point(501)))
    def test_bad_core_network_never_marks_status_ready(self):
        self.runtime.sweep(self.index);self.runtime.observed['observedSynchronized']=False;self.runtime.stop=ScriptedStop([False]);self.core.call=Mock(return_value={'chain':'testnet4','blocks':0,'headers':0,'bestblockhash':self.rules.value['genesis'],'initialblockdownload':False})
        with self.assertRaises(Incomplete):self.runtime.wait_for_tip_change(self.index.tip)
        self.assertFalse(self.runtime.checkpoint()['observedSynchronized'])
    def test_idle_probe_cannot_restore_a_failed_readiness_flag(self):
        self.runtime.sweep(self.index);self.runtime.observed['available']=False;self.runtime.observed['observedSynchronized']=False;self.probe_core();self.runtime.stop=ScriptedStop([False]);self.runtime.wait_for_tip_change(self.index.tip);self.assertFalse(self.runtime.checkpoint()['observedSynchronized']);self.assertFalse(self.runtime.checkpoint()['available'])
    def test_outage_backoff_is_bounded_and_keeps_committed_identity(self):
        self.runtime.sweep(self.index);tip=self.index.tip;self.runtime.stop=ScriptedStop([False,False,False,True]);self.runtime.sweep=Mock(side_effect=Incomplete('fixture unavailable'))
        with patch('q20.runtime.Index',return_value=self.index),patch('builtins.print'):self.runtime.run()
        self.assertEqual(self.runtime.stop.delays,[5,10,20,30]);state=self.runtime.checkpoint();self.assertFalse(state['available']);self.assertFalse(state['observedSynchronized']);self.assertEqual((state['indexHeight'],state['indexHash']),tip);self.assertEqual(state['rulesFingerprint'],self.rules.fingerprint)
