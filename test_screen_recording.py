import unittest
from screen_recording import detect, prefer_non_screen

class ScreenRecording(unittest.TestCase):
    def test_explicit_and_ambiguous_metadata(self):
        self.assertTrue(detect('ScreenRecording_20260101.mp4', {}))
        info = {'format': {'tags': {'major_brand': 'mp42'}}, 'streams': [
            {'codec_type': 'video', 'width': 588, 'height': 1280,
             'tags': {'handler_name': 'Core Media Video'}}]}
        self.assertTrue(detect('renamed.mp4', info))
        info['format']['tags']['com.apple.quicktime.model'] = 'iPhone'
        self.assertFalse(detect('camera.mp4', info))
        self.assertFalse(detect('unknown.mp4', {}))

    def test_alternative_and_fallback(self):
        suspect = dict(kind='video', source='mobile', duration=10, screen_recording_reason='suspect')
        clean = dict(kind='video', source='mobile', duration=10)
        self.assertEqual(prefer_non_screen([suspect, clean]), [clean])
        self.assertEqual(prefer_non_screen([suspect]), [suspect])
        short = dict(clean, duration=1)
        self.assertEqual(prefer_non_screen([suspect, short]), [suspect, short])
        camera = dict(clean, source='camera')
        self.assertEqual(prefer_non_screen([suspect, camera]), [suspect, camera])

if __name__ == '__main__':
    unittest.main()
