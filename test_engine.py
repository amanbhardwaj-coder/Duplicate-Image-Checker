import unittest
from unittest.mock import patch
import imagehash
import numpy as np
from engine import scan, csv_bytes

class ScannerTests(unittest.TestCase):
    def test_duplicates_errors_and_source_preservation(self):
        rows=[['Stock','One','Two','Three'],['001.0','a','b','broken'],['002','b','','']]
        original=[r[:] for r in rows]
        def fake(url):
            if url=='broken': raise ValueError('bad image')
            return imagehash.ImageHash(np.zeros((8,8),dtype=bool))
        with patch('engine.get_hash', side_effect=fake):
            matches,errors=scan(rows,1,0,[1,2,3],2,4)
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]['col'],2)
        self.assertEqual(matches[0]['original_col'],1)
        self.assertEqual(len(errors),1)
        self.assertEqual(rows,original)
        self.assertIn(b'001.0',csv_bytes(rows))
    def test_threshold(self):
        h1=imagehash.ImageHash(np.zeros((8,8),dtype=bool))
        bits=np.zeros((8,8),dtype=bool); bits[0,:3]=True
        with patch('engine.get_hash', side_effect=lambda u: h1 if u=='a' else imagehash.ImageHash(bits)):
            matches,_=scan([['s','a','b']],0,0,[1,2],2,4)
        self.assertFalse(matches)

if __name__=='__main__': unittest.main()
