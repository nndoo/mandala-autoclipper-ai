import assert from 'node:assert/strict';
import test from 'node:test';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, writeFile, readFile, rm, symlink } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { qualityReviewPrompt } from '../dist/qa-prompt.js';
import { describe9RouterVideo } from '../dist/transport.js';
const projectRoot=fileURLToPath(new URL('../../../../',import.meta.url));
const root=projectRoot+'data/qa/stage56/';
const sha=b=>createHash('sha256').update(b).digest('hex');
const video=Buffer.alloc(2048,2);
const template=()=>({contract_version:'0.1.0',kind:'stage56_multimodal_qa_request',media:{role:'edited_output',bytes:video.length,sha256:sha(video)},prompt:'Review actual attached edited video; no production approval',prompt_sha256:sha('Review actual attached edited video; no production approval')});
async function fixture(fn){
 await mkdir(root,{recursive:true});
 const temp=await mkdtemp(root+'.plugin-qa-');const path=temp+'/request.json';const prior={...process.env};
 try{let data=template();await writeFile(path,JSON.stringify(data));process.env.MANDALA_VIDEO_QA_REQUEST_FILE=path;process.env.MANDALA_VIDEO_QA_REQUEST_SHA256=sha(JSON.stringify(data));process.env.MANDALA_VIDEO_ANALYSIS_MODE='quality_qa_v01';process.env.MANDALA_VIDEO_QA_PROJECT_ROOT=projectRoot;
 await fn({path,data,save:async()=>{await writeFile(path,JSON.stringify(data));process.env.MANDALA_VIDEO_QA_REQUEST_SHA256=sha(JSON.stringify(data));}});
 }finally{for(const key of ['MANDALA_VIDEO_QA_REQUEST_FILE','MANDALA_VIDEO_QA_REQUEST_SHA256','MANDALA_VIDEO_ANALYSIS_MODE','MANDALA_VIDEO_QA_PROJECT_ROOT']){if(prior[key]===undefined)delete process.env[key];else process.env[key]=prior[key];}await rm(temp,{recursive:true,force:true});}
}
test('QA prompt binds exact request and MP4',async()=>fixture(async({data})=>assert.equal(await qualityReviewPrompt(video),data.prompt)));
test('QA mode forwards bound Reviewer prompt, not default Analyst',async()=>fixture(async({data})=>{
 let body;await describe9RouterVideo({buffer:video,mime:'video/mp4',baseUrl:'https://router.example/v1',apiKey:'test',model:'openclaw',fetchFn:async(_url,opts)=>{body=JSON.parse(opts.body);return new Response(JSON.stringify({choices:[{message:{content:'{}'}}]}),{status:200});}});
 assert.equal(body.messages[0].content[0].text,data.prompt);assert.match(body.messages[0].content[1].image_url.url,/^data:video\/mp4;base64,/);
 assert.deepEqual(Buffer.from(body.messages[0].content[1].image_url.url.split(',')[1],'base64'),video);
 assert.equal(body.model,'openclaw');assert.equal(body.stream,false);
}));
test('QA missing receipt rejected before network',async()=>fixture(async()=>{delete process.env.MANDALA_VIDEO_QA_REQUEST_SHA256;await assert.rejects(qualityReviewPrompt(video),/receipt missing/);}));
test('QA wrong MP4 rejected',async()=>fixture(async()=>assert.rejects(qualityReviewPrompt(Buffer.alloc(2048,3)),/binding invalid/)));
test('QA changed request rejected',async()=>fixture(async({path})=>{await writeFile(path,'{}');await assert.rejects(qualityReviewPrompt(video),/changed/);}));
test('QA changed prompt hash rejected',async()=>fixture(async({data,save})=>{data.prompt+='changed';await save();await assert.rejects(qualityReviewPrompt(video),/binding invalid/);}));
test('QA role mismatch rejected',async()=>fixture(async({data,save})=>{data.media.role='both';await save();await assert.rejects(qualityReviewPrompt(video),/binding invalid/);}));
test('QA request outside project rejected',async()=>fixture(async()=>{process.env.MANDALA_VIDEO_QA_REQUEST_FILE='/etc/passwd';await assert.rejects(qualityReviewPrompt(video),/outside project/);}));
test('QA traversal rejected',async()=>fixture(async()=>{process.env.MANDALA_VIDEO_QA_REQUEST_FILE='data/../request.json';await assert.rejects(qualityReviewPrompt(video),/Unsafe/);}));
test('QA secret file path rejected',async()=>fixture(async()=>{process.env.MANDALA_VIDEO_QA_REQUEST_FILE='.env.asr';await assert.rejects(qualityReviewPrompt(video),/Unsafe/);}));
test('QA symlink rejected',async()=>fixture(async({path})=>{const link=path+'.link';await symlink(path,link);process.env.MANDALA_VIDEO_QA_REQUEST_FILE=link;await assert.rejects(qualityReviewPrompt(video),/symlink/);}));
test('QA oversized prompt rejected',async()=>fixture(async({data,save})=>{data.prompt='x'.repeat(65537);data.prompt_sha256=sha(data.prompt);await save();await assert.rejects(qualityReviewPrompt(video),/binding invalid/);}));
test('QA credential-like prompt rejected',async()=>fixture(async({data,save})=>{data.prompt='Bearer secret-test-value';data.prompt_sha256=sha(data.prompt);await save();await assert.rejects(qualityReviewPrompt(video),/credential/);}));

test('QA missing approved root rejected',async()=>fixture(async()=>{delete process.env.MANDALA_VIDEO_QA_PROJECT_ROOT;await assert.rejects(qualityReviewPrompt(video),/root missing/);}));
test('QA relative root rejected',async()=>fixture(async()=>{process.env.MANDALA_VIDEO_QA_PROJECT_ROOT='relative';await assert.rejects(qualityReviewPrompt(video),/unsafe/);}));
test('QA loader relocation cannot change approved project boundary',async()=>fixture(async({path,data})=>{
 const relocated=path+'.relocated.mjs';await writeFile(relocated,await readFile(new URL('../dist/qa-prompt.js',import.meta.url)));
 const module=await import(relocated);assert.equal(await module.qualityReviewPrompt(video),data.prompt);
}));
