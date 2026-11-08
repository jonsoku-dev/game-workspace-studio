// Test fixture only; dependencies are installed in a separate temporary directory.
const {createRequire} = require('node:module');
const {resolve} = require('node:path');
const {readFile} = require('node:fs/promises');
const req = createRequire(resolve(process.argv[2], 'package.json'));
const {NodeIO} = req('@gltf-transform/core');
const {ALL_EXTENSIONS, EXTMeshoptCompression} = req('@gltf-transform/extensions');
const {MeshoptEncoder} = req('meshoptimizer');
(async () => {
  await MeshoptEncoder.ready;
  const io = new NodeIO().registerExtensions(ALL_EXTENSIONS)
    .registerDependencies({'meshopt.encoder': MeshoptEncoder});
  const doc = await io.readBinary(await readFile(process.argv[3]));
  doc.createExtension(EXTMeshoptCompression).setRequired(true);
  await io.write(process.argv[4], doc);
})().catch(error => { console.error(error); process.exitCode = 1; });
