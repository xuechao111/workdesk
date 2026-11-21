// Compatibility launcher; all metric rules live in the shared Python pipeline.
import path from 'node:path';
import fs from 'node:fs';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const dataDir=path.resolve(process.argv[2]||'../data');
const classes=path.resolve(process.argv[3]||path.join(dataDir,'classes.json'));
const candidates=[process.env.HF_PYTHON,process.env.PYTHON,path.join(root,'runtime','python','python.exe'),path.resolve(path.dirname(process.execPath),'../../python/python.exe'),path.resolve(path.dirname(process.execPath),'../../python/bin/python3')].filter(Boolean);
const python=candidates.find(file=>fs.existsSync(file))||(process.platform==='win32'?'python':'python3');
const result=spawnSync(python,[path.join(root,'build_teaching_class_tables.py'),'--data-dir',dataDir,'--classes',classes,'--raw-file',process.argv[4]||'group-lessons-raw.json'],{stdio:'inherit',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
if(result.error)throw result.error;
process.exit(result.status??1);
