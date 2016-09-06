import json

from tests.unit.chroma_api.chroma_api_test_case import ChromaApiTestCase
from tests.unit.chroma_core.helpers import synthetic_host, synthetic_volume_full
from tests.unit.chroma_core.helpers import create_targets_patch
from chroma_core.models import VolumeNode


class TestVolumeNodeDelete(ChromaApiTestCase):
    """
    Make sure a deleted VolumeNode means a Volume doesn't show up as being on that Volume.
    """

    def _get_volumes(self, host_id=None):
        if host_id:
            data = {'host_id': host_id}
        else:
            data = {}

        response = self.api_client.get("/api/volume/", data=data)

        return json.loads(response.content)['objects']

    def test_deleted_volumenode(self):
        """
        Test deleting a VolumeNode means the volume API does not return it.
        """
        host0 = synthetic_host('host0')
        host1 = synthetic_host('host1')
        synthetic_volume_full(host0, host1)

        self.assertEqual(1, len(self._get_volumes()))
        self.assertEqual(1, len(self._get_volumes(host0.id)))
        self.assertEqual(1, len(self._get_volumes(host1.id)))

        VolumeNode.objects.get(host_id=host0.id).mark_deleted()

        self.assertEqual(0, len(self._get_volumes(host0.id)))
        self.assertEqual(1, len(self._get_volumes(host1.id)))

        VolumeNode.objects.filter(host_id=host1.id).delete()
        self.assertEqual(0, len(self._get_volumes(host1.id)))

    @create_targets_patch
    def test_select_by_filesystem(self):
        """Test selecting host by filesystem with valid and invalid filesystem ids."""
        self.create_simple_filesystem(synthetic_host('myserver'))

        response = self.api_client.get('/api/volume/', data={'filesystem_id': self.fs.id})
        self.assertHttpOK(response)
        content = json.loads(response.content)
        self.assertEqual(3, len(content['objects']))

        response = self.api_client.get('/api/volume/', data={'filesystem_id': -1000})
        self.assertHttpOK(response)
        content = json.loads(response.content)
        self.assertEqual(0, len(content['objects']))