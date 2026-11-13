import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const background=fs.readFileSync(new URL('../chrome-extension/background.js',import.meta.url),'utf8');
const fetcher=fs.readFileSync(new URL('../scripts/fetch_group_lessons.mjs',import.meta.url),'utf8');

test('course detail CRM requests stay within the API maximum page size',()=>{
  assert.match(background,/course-detail\?page=\$\{pageNo\}&limit=\$\{detailPageSize\}/);
  assert.match(background,/const detailPageSize=100/);
  assert.match(fetcher,/const items=\[\]; const pageSize=100/);
  assert.doesNotMatch(background,/course-detail\?page=\$\{pageNo\}&limit=500/);
  assert.doesNotMatch(fetcher,/course-detail\?page=\$\{pageNo\}&limit=500/);
});
