# Licensed to the StackStorm, Inc ('StackStorm') under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import

import mock

import st2tests

# XXX: actionsensor import depends on config being setup.
import st2tests.config as tests_config
tests_config.parse_args()

from tests.unit import base

from st2common.bootstrap import actionsregistrar
from st2common.bootstrap import runnersregistrar
from st2common.constants import action as ac_const
from st2common.models.db import liveaction as lv_db_models
from st2common.persistence import liveaction as lv_db_access
from st2common.persistence import workflow as wf_db_access
from st2common.runners import base as runners
from st2common.services import action as ac_svc
from st2common.transport import liveaction as lv_ac_xport
from st2common.transport import publishers
from st2tests.mocks import liveaction as mock_lv_ac_xport


TEST_FIXTURES = {
    'workflows': [
        'sequential.yaml'
    ],
    'actions': [
        'sequential.yaml'
    ]
}

TEST_PACK = 'orchestra_tests'
TEST_PACK_PATH = st2tests.fixturesloader.get_fixtures_packs_base_path() + '/' + TEST_PACK

PACKS = [
    TEST_PACK_PATH,
    st2tests.fixturesloader.get_fixtures_packs_base_path() + '/core'
]


@mock.patch.object(
    publishers.CUDPublisher,
    'publish_update',
    mock.MagicMock(return_value=None))
@mock.patch.object(
    publishers.CUDPublisher,
    'publish_create',
    mock.MagicMock(side_effect=mock_lv_ac_xport.MockLiveActionPublisher.publish_create))
@mock.patch.object(
    lv_ac_xport.LiveActionPublisher,
    'publish_state',
    mock.MagicMock(side_effect=mock_lv_ac_xport.MockLiveActionPublisher.publish_state))
class OrchestraRunnerTest(st2tests.DbTestCase):

    @classmethod
    def setUpClass(cls):
        super(OrchestraRunnerTest, cls).setUpClass()

        # Register runners.
        runnersregistrar.register_runners()

        # Register test pack(s).
        actions_registrar = actionsregistrar.ActionsRegistrar(
            use_pack_cache=False,
            fail_on_failure=True
        )

        for pack in PACKS:
            actions_registrar.register_from_pack(pack)

    @classmethod
    def get_runner_class(cls, runner_name):
        return runners.get_runner(runner_name, runner_name).__class__

    def test_launch_workflow(self):
        wf_meta = base.get_wf_fixture_meta_data(TEST_PACK_PATH, TEST_FIXTURES['workflows'][0])
        lv_ac_db = lv_db_models.LiveActionDB(action=wf_meta['name'])
        lv_ac_db, ac_ex_db = ac_svc.request(lv_ac_db)
        lv_ac_db = lv_db_access.LiveAction.get_by_id(str(lv_ac_db.id))

        self.assertTrue(lv_ac_db.action_is_workflow)
        self.assertEqual(lv_ac_db.status, ac_const.LIVEACTION_STATUS_RUNNING, lv_ac_db.result)

        wf_ex_dbs = wf_db_access.WorkflowExecution.query(action_execution=str(ac_ex_db.id))
        wf_ex_db = wf_ex_dbs[0]

        # Check required attributes.
        self.assertEqual(len(wf_ex_dbs), 1)
        self.assertIsNotNone(wf_ex_db.id)
        self.assertGreater(wf_ex_db.rev, 0)
        self.assertEqual(wf_ex_db.action_execution, str(ac_ex_db.id))
        self.assertEqual(wf_ex_db.status, ac_const.LIVEACTION_STATUS_REQUESTED)

        # Check context.
        self.assertIn('workflow_execution', lv_ac_db.context)
        self.assertEqual(lv_ac_db.context['workflow_execution'], str(wf_ex_db.id))

        # Check graph.
        self.assertIsNotNone(wf_ex_db.graph)
        self.assertTrue(isinstance(wf_ex_db.graph, dict))
        self.assertIn('nodes', wf_ex_db.graph)
        self.assertIn('adjacency', wf_ex_db.graph)

        # Check task flow.
        self.assertIsNotNone(wf_ex_db.flow)
        self.assertTrue(isinstance(wf_ex_db.flow, dict))
        self.assertIn('tasks', wf_ex_db.flow)
        self.assertIn('sequence', wf_ex_db.flow)

        # Check input.
        expected_input = {
            'who': 'Stanley'
        }

        self.assertDictEqual(wf_ex_db.input, expected_input)