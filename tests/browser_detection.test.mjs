import {test} from 'node:test';
import assert from 'node:assert/strict';
import {decode,iou} from '../browser-client/detection.mjs';
import {EFFORTS,effortInterval} from '../browser-client/effort.mjs';

test('Five effort levels have strictly increasing sampling work',()=>{
  const intervals=Object.keys(EFFORTS).map(effortInterval);
  assert.equal(intervals.length,5);
  assert.ok(intervals.every((value,i)=>value>0&&(i===0||value<intervals[i-1])));
  assert.equal(effortInterval('invalid'),600);
});

test('Rejects incompatible model outputs',()=>assert.throws(()=>decode([], [1,300,6],640,480)));
test('Correctly decodes person, NMS duplicates, and excludes another class',()=>{
  const n=3,data=new Float32Array(84*n);
  for(let i=0;i<n;i++){data[i]=160;data[n+i]=160;data[2*n+i]=80;data[3*n+i]=80;data[4*n+i]=.8;}
  data[5*n+2]=.9;
  const boxes=decode(data,[1,84,n],640,480);
  assert.equal(boxes.length,1);
  assert.deepEqual(boxes[0].slice(0,4),[240,160,400,320]);
});
test('Filters low confidence and invalid coordinates',()=>{
  const data=new Float32Array(84);data[4]=.2;
  assert.equal(decode(data,[1,84,1],320,320).length,0);
  data[4]=.9;data[2]=NaN;
  assert.equal(decode(data,[1,84,1],320,320).length,0);
});
test('Intersection over union',()=>{
  assert.equal(iou([0,0,10,10],[0,0,10,10]),1);
  assert.equal(iou([0,0,10,10],[20,20,30,30]),0);
});
