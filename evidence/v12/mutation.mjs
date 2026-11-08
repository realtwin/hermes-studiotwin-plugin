import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
const paths=['src/lib/ui-tokens.ts','src/pages/asset-inspector.tsx','desktop/plugin.js'];
const saved=new Map(paths.map(p=>[p,fs.readFileSync(p)]));
try {
  for(const p of paths) {
    const base=spawnSync('git',['show',`188f09d0857826becce48595d870e011f825bd64:${p}`], {maxBuffer: 16 * 1024 * 1024});
    if(base.status!==0) throw Error('Cannot read baseline '+p);
    fs.writeFileSync(p,base.stdout);
  }
  const result=spawnSync('npx',['vitest','run','tests/workspace/v11-studio.test.ts','-t','V12'],{encoding:'utf8',timeout:180000});
  fs.writeFileSync('.verification/v12/mutation.log',result.stdout+result.stderr);
  console.log(result.stdout+result.stderr);
  if(result.status!==1 || !result.stdout.includes('3 failed')) throw Error('Mutation did not trip all three regressions');
  console.log('PASS: baseline mutation detected all three regressions');
} finally { for(const [p,bytes] of saved) fs.writeFileSync(p,bytes); }
