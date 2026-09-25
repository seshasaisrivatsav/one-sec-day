import copy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import core


class EditorTests(unittest.TestCase):
    def record(self,path,source='mobile',kind='video',duration=5):
        return dict(path=str(path),source=source,kind=kind,duration=duration,day='2020-02-01',
                    capture_local='2020-02-01T10:20:00',date_source='filename',warnings='',width=1920,height=1080)

    def test_selection_priority_and_manual_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            a=Path(temp)/'a.mp4';b=Path(temp)/'b.mp4';a.touch();b.touch()
            project=core.fresh();project['records']=[self.record(a),self.record(b,'camera')]
            with patch.object(core.highlights,'quality',return_value=2):
                mobile=core.automatic(project,'2020-02',temp)
                self.assertEqual(mobile['selections']['2020-02-01']['path'],str(a))
                mobile['priority']='camera'
                camera=core.automatic(mobile,'2020-02',temp)
                self.assertEqual(camera['selections']['2020-02-01']['path'],str(b))
                core.select(camera,project['records'][0],1.25)
                rerun=core.automatic(camera,'2020-02',temp)
                self.assertEqual(rerun['selections']['2020-02-01']['start_seconds'],1.25)
                self.assertEqual(rerun['selections']['2020-02-01']['path'],str(a))
                self.assertEqual(len(core.rows(rerun,'2020-02')),29)

    def test_camera_video_precedes_mobile_photo(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'clip.mp4';path.touch()
            project=core.fresh();project['records']=[self.record(path,'camera'),self.record('photo.jpg',kind='photo')]
            with patch.object(core.highlights,'quality',return_value=2):
                result=core.automatic(project,'2020-02',temp)
            self.assertEqual(result['selections']['2020-02-01']['source'],'camera')

    def test_invalid_windows_and_project_roundtrip(self):
        project=core.fresh();rec=self.record('clip.mp4')
        with self.assertRaises(ValueError):core.select(project,rec,4.1)
        with self.assertRaises(ValueError):core.select(project,self.record('short.mp4',duration=1),0)
        core.select(project,rec,2.4)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'project.json';core.save(path,project)
            self.assertEqual(core.load(path),project)

    def test_failed_preferred_video_falls_back(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'camera.mp4';path.touch()
            project=core.fresh();project['records']=[self.record(Path(temp)/'missing.mp4'),self.record(path,'camera')]
            with patch.object(core.highlights,'quality',return_value=2):
                result=core.automatic(project,'2020-02',temp)
            self.assertEqual(result['selections']['2020-02-01']['path'],str(path))

    def test_undated_scan_and_overlap_dedup(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'source';folder.mkdir();Image.new('RGB',(100,80)).save(folder/'unknown.png')
            source=dict(path=str(folder),type='mobile',timezone='America/Chicago',video_clock='utc')
            records,issues=core.scan([source,source],Path(temp)/'cache')
            self.assertEqual(len(records),1);self.assertEqual(records[0]['day'],'');self.assertEqual(issues,[])


if __name__=='__main__':unittest.main()
