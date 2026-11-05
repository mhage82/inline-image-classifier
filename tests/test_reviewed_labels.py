import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from scripts.import_reviewed_labels import read_workbook
from scripts.merge_annotations import merge
from scripts.process_annotations import process


class ReviewedTests(unittest.TestCase):
    def test_excel_numeric_and_dropped_reading(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "review.xlsx"
            namespace = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            cells = lambda values, row: ''.join(f'<c r="{chr(65+i)}{row}" t="inlineStr"><is><t>{v}</t></is></c>' for i,v in enumerate(values))
            with ZipFile(path, 'w') as z:
                z.writestr('xl/workbook.xml', f'<workbook {namespace} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="labels" r:id="r1"/></sheets></workbook>')
                z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
                rows = [cells(['image_id','filename','artifact_present','resolution_status'],1), cells(['one','one.jpg','1.0','reviewed'],2), cells(['two','two.jpg','N/A','dropped'],3)]
                z.writestr('xl/worksheets/sheet1.xml',f'<worksheet {namespace}><sheetData>'+''.join(f'<row r="{i}">{r}</row>' for i,r in enumerate(rows,1))+'</sheetData></worksheet>')
            result = read_workbook(path)
            self.assertEqual([r['annotation']['labels'] for r in result], [[1],['dropped']])

    def test_reviewed_layer_survives_rebuild_and_dropped_is_not_review_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);raw=root/'raw';raw.mkdir()
            row={'image_id':'one','filename':'one.jpg','labels':['lens_contamination'],'artifact_judgment':'present','status':'annotated'}
            submission={'schema_version':1,'submission_id':'s','dataset_id':'current','group_id':'g','group_version':'v','annotator_id':'a','guidelines_version':'2','submitted_at':'time','annotations':{'one':row}}
            (raw/'one.json').write_text(json.dumps(submission))
            review={'source_row':2,'resolution_status':'dropped','annotation':{'image_id':'one','filename':'one.jpg','labels':['dropped'],'status':'dropped'}}
            (root/'reviewed_labels.json').write_text(json.dumps({'schema_version':1,'reviewed_annotations':[review]}))
            first=merge(raw,root/'master.json');second=merge(raw,root/'master.json')
            self.assertEqual(first,second)
            self.assertEqual(first['annotations'][0]['annotation'],row)
            self.assertEqual(first['reviewed_annotations'][0]['annotation']['labels'],['dropped'])
            output,queue=process(first,{'reference_dataset_id':'current'})
            self.assertEqual(output['images'][0]['resolution_status'],'dropped')
            self.assertEqual(queue,[])
            self.assertEqual(output['summary']['dropped_image_count'],1)

    def test_binary_review_overrides_final_target_not_student_votes(self):
        original={'annotator_id':'a','submission_id':'s','dataset_id':'current','annotation':{'image_id':'one','filename':'one.jpg','labels':['lens_contamination'],'artifact_judgment':'present','status':'annotated'}}
        review={'annotation':{'image_id':'one','labels':[0]}}
        output,_=process({'annotations':[original],'reviewed_annotations':[review]},{'reference_dataset_id':'current'})
        row=output['images'][0]
        self.assertEqual(row['artifact_present'],0)
        self.assertEqual(row['annotator_votes'][0]['artifact_present'],1)
        self.assertEqual(row['annotations'],[original])


if __name__=='__main__':unittest.main()
