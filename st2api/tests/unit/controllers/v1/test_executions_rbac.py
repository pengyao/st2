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

import mock
from oslo_config import cfg

from six.moves import http_client

from st2common.validators.api import action as action_validator
from st2common.rbac.types import PermissionType
from st2common.rbac.types import ResourceType
from st2common.models.db.auth import UserDB
from st2common.persistence.auth import User
from st2common.models.db.rbac import RoleDB
from st2common.models.db.rbac import UserRoleAssignmentDB
from st2common.models.db.rbac import PermissionGrantDB
from st2common.persistence.rbac import UserRoleAssignment
from st2common.persistence.rbac import Role
from st2common.persistence.rbac import PermissionGrant
from st2common.transport.publishers import PoolPublisher
from tests.base import APIControllerWithRBACTestCase
from tests.base import BaseActionExecutionControllerTestCase
from st2tests.fixturesloader import FixturesLoader


FIXTURES_PACK = 'generic'
TEST_FIXTURES = {
    'runners': ['testrunner1.yaml'],
    'actions': ['action1.yaml', 'local.yaml']
}


@mock.patch.object(PoolPublisher, 'publish', mock.MagicMock())
class ActionExecutionRBACControllerTestCase(BaseActionExecutionControllerTestCase,
                                            APIControllerWithRBACTestCase):

    fixtures_loader = FixturesLoader()

    @mock.patch.object(action_validator, 'validate_action', mock.MagicMock(
        return_value=True))
    def setUp(self):
        super(ActionExecutionRBACControllerTestCase, self).setUp()

        self.fixtures_loader.save_fixtures_to_db(fixtures_pack=FIXTURES_PACK,
                                                 fixtures_dict=TEST_FIXTURES)

        # Insert mock users, roles and assignments

        # Users
        user_1_db = UserDB(name='multiple_roles')
        user_1_db = User.add_or_update(user_1_db)
        self.users['multiple_roles'] = user_1_db

        user_2_db = UserDB(name='user_two')
        user_2_db = User.add_or_update(user_2_db)
        self.users['user_two'] = user_2_db

        user_3_db = UserDB(name='user_three')
        user_3_db = User.add_or_update(user_3_db)
        self.users['user_three'] = user_3_db

        # Roles
        roles = ['role_1', 'role_2', 'role_3']
        for role in roles:
            role_db = RoleDB(name=role)
            Role.add_or_update(role_db)

        # action_execute on parent pack
        grant_1_db = PermissionGrantDB(resource_uid='pack:wolfpack',
                                       resource_type=ResourceType.PACK,
                                       permission_types=[PermissionType.ACTION_EXECUTE])
        grant_1_db = PermissionGrant.add_or_update(grant_1_db)
        grant_2_db = PermissionGrantDB(resource_uid=None,
                                     resource_type=ResourceType.EXECUTION,
                                     permission_types=[PermissionType.EXECUTION_LIST])
        grant_2_db = PermissionGrant.add_or_update(grant_2_db)
        permission_grants = [str(grant_1_db.id), str(grant_2_db.id)]

        role_1_db = RoleDB(name='role_4', permission_grants=permission_grants)
        role_1_db = Role.add_or_update(role_1_db)
        self.roles['role_4'] = role_1_db

        # Role assignments
        role_assignment_db = UserRoleAssignmentDB(
            user=user_1_db.name,
            role='admin',
            source='assignments/%s.yaml' % user_1_db.name)
        UserRoleAssignment.add_or_update(role_assignment_db)

        for role in roles:
            role_assignment_db = UserRoleAssignmentDB(
                user=user_1_db.name,
                role=role,
                source='assignments/%s.yaml' % user_1_db.name)
            UserRoleAssignment.add_or_update(role_assignment_db)

        role_assignment_db = UserRoleAssignmentDB(
            user=user_2_db.name,
            role='role_4',
            source='assignments/%s.yaml' % user_2_db.name)
        UserRoleAssignment.add_or_update(role_assignment_db)

        role_assignment_db = UserRoleAssignmentDB(
            user=user_3_db.name,
            role='role_4',
            source='assignments/%s.yaml' % user_2_db.name)
        UserRoleAssignment.add_or_update(role_assignment_db)

    def test_post_rbac_info_in_context_success(self):
        # When RBAC is enabled, additional RBAC related info should be included in action_context
        data = {
            'action': 'wolfpack.action-1',
            'parameters': {
                'actionstr': 'foo'
            }
        }

        # User with one role assignment
        user_db = self.users['admin']
        self.use_user(user_db)

        resp = self._do_post(data)
        self.assertEqual(resp.status_int, 201)

        expected_context = {
            'pack': 'wolfpack',
            'user': 'admin',
            'rbac': {
                'user': 'admin',
                'roles': ['admin']
            }
        }

        self.assertEqual(resp.json['context'], expected_context)

        # User with multiple role assignments
        user_db = self.users['multiple_roles']
        self.use_user(user_db)

        resp = self._do_post(data)
        self.assertEqual(resp.status_int, 201)

        expected_context = {
            'pack': 'wolfpack',
            'user': 'multiple_roles',
            'rbac': {
                'user': 'multiple_roles',
                'roles': ['admin', 'role_1', 'role_2', 'role_3']
            }
        }

        self.assertEqual(resp.json['context'], expected_context)

    def test_get_all_limit_minus_one(self):
        user_db = self.users['observer']
        self.use_user(user_db)

        resp = self.app.get('/v1/actionexecutions?limit=-1', expect_errors=True)
        self.assertEqual(resp.status_code, http_client.FORBIDDEN)

        user_db = self.users['admin']
        self.use_user(user_db)

        resp = self.app.get('/v1/actionexecutions?limit=-1')
        self.assertEqual(resp.status_code, http_client.OK)

    def test_get_respective_actions_with_permission_isolation(self):
        cfg.CONF.set_override(name='permission_isolation', override=True, group='rbac')

        data = {
            'action': 'wolfpack.action-1',
            'parameters': {
                'actionstr': 'foo'
            }
        }

        # User with admin role assignment
        user_db = self.users['admin']
        self.use_user(user_db)

        resp = self._do_post(data)
        self.assertEqual(resp.status_code, http_client.CREATED)

        # User with multiple roles assignment
        user_db = self.users['user_two']
        self.use_user(user_db)

        resp = self._do_post(data)
        self.assertEqual(resp.status_code, http_client.CREATED)
        resp = self._do_post(data)
        self.assertEqual(resp.status_code, http_client.CREATED)

        # User two
        user_db = self.users['user_three']
        self.use_user(user_db)

        resp = self._do_post(data)
        self.assertEqual(resp.status_code, http_client.CREATED)
        resp = self._do_post(data)
        self.assertEqual(resp.status_code, http_client.CREATED)

        # 1. Admin can view all
        user_db = self.users['admin']
        self.use_user(user_db)

        resp = self.app.get('/v1/actionexecutions?limit=100')
        self.assertEqual(len(resp.json), (1 + 2 + 2))
        self.assertEqual(resp.json[0]['context']['user'], 'user_three')
        self.assertEqual(resp.json[1]['context']['user'], 'user_three')
        self.assertEqual(resp.json[2]['context']['user'], 'user_two')
        self.assertEqual(resp.json[3]['context']['user'], 'user_two')
        self.assertEqual(resp.json[4]['context']['user'], 'admin')

        # 2. System user can view all
        user_db = self.users['system_user']
        self.use_user(user_db)

        resp = self.app.get('/v1/actionexecutions?limit=100')
        self.assertEqual(len(resp.json), (1 + 2 + 2))
        self.assertEqual(resp.json[0]['context']['user'], 'user_three')
        self.assertEqual(resp.json[1]['context']['user'], 'user_three')
        self.assertEqual(resp.json[2]['context']['user'], 'user_two')
        self.assertEqual(resp.json[3]['context']['user'], 'user_two')
        self.assertEqual(resp.json[4]['context']['user'], 'admin')

        # 3. User two can only view their own
        user_db = self.users['user_two']
        self.use_user(user_db)

        resp = self.app.get('/v1/actionexecutions?limit=100')
        self.assertEqual(len(resp.json), 2)
        self.assertEqual(resp.json[0]['context']['user'], 'user_two')
        self.assertEqual(resp.json[1]['context']['user'], 'user_two')

        # 4. User three can only view their own
        user_db = self.users['user_three']
        self.use_user(user_db)

        resp = self.app.get('/v1/actionexecutions?limit=100')
        self.assertEqual(len(resp.json), 2)
        self.assertEqual(resp.json[0]['context']['user'], 'user_three')
        self.assertEqual(resp.json[1]['context']['user'], 'user_three')
