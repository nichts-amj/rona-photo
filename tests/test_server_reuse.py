import io
import json
import unittest
from unittest.mock import patch
from web_app import BACKEND_REVISION, check_existing_studio


def response(data):return io.StringIO(json.dumps(data))


class ServerReuseTests(unittest.TestCase):
    def test_matching_backend_can_be_reopened(self):
        with patch('web_app.urllib.request.urlopen',return_value=response({'app':'rona-studio','backend_revision':BACKEND_REVISION})) as request:
            self.assertEqual(check_existing_studio('http://127.0.0.1:8772')['app'],'rona-studio')
            self.assertEqual(request.call_count,1)

    def test_changed_backend_requires_restart_instead_of_opening_stale_ui(self):
        with patch('web_app.urllib.request.urlopen',return_value=response({'app':'rona-studio','backend_revision':'old'})):
            with self.assertRaisesRegex(RuntimeError,'versi lama masih berjalan'):check_existing_studio('http://127.0.0.1:8772')

    def test_legacy_server_without_shared_history_cannot_be_reused(self):
        with patch('web_app.urllib.request.urlopen',side_effect=[response({'app':'rona-studio'}),OSError('404')]):
            with self.assertRaisesRegex(RuntimeError,'belum mendukung Riwayat bersama'):check_existing_studio('http://127.0.0.1:8772')

    def test_legacy_server_with_current_history_api_remains_usable(self):
        with patch('web_app.urllib.request.urlopen',side_effect=[response({'app':'rona-studio'}),response({'items':[]})]) as request:
            self.assertEqual(check_existing_studio('http://127.0.0.1:8772')['app'],'rona-studio')
            self.assertEqual(request.call_count,2)

    def test_unrelated_service_is_not_treated_as_rona(self):
        with patch('web_app.urllib.request.urlopen',return_value=response({'app':'another-app'})):
            with self.assertRaisesRegex(RuntimeError,'aplikasi lain'):check_existing_studio('http://127.0.0.1:8772')


if __name__=='__main__':unittest.main()
