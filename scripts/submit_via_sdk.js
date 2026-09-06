// submit_via_sdk.js — submit register_artist using genlayer-js directly.
// Usage: node submit_via_sdk.js <privkey_hex_no_0x> <contract> <name> <did> <audio_hash_hex_no_0x> <wallet> <src1> <h1> <src2> <h2>

const path = require('path');
const sdk = require('/usr/local/lib/node_modules/genlayer/node_modules/genlayer-js');

const [
  ,
  privkeyHex,
  contractAddr,
  artistName,
  did,
  audioHashHex,
  wallet,
  src1, h1, src2, h2
] = process.argv;

if (!privkeyHex || !contractAddr) {
  console.error('Usage: node submit_via_sdk.js <privkey> <contract> ...');
  process.exit(1);
}

const sources = {
  apple_music: 'https://music.apple.com/us/artist/burial/468355684?uo=4',
  musicbrainz: 'https://musicbrainz.org/artist/9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6',
};

const args = [
  did, artistName, '0x' + audioHashHex, sources, wallet,
  src1, h1, src2, h2, true
];

(async () => {
  try {
    const pk = privkeyHex.startsWith('0x') ? privkeyHex : '0x' + privkeyHex;
    const account = sdk.createAccount(pk);
    console.log('account address:', account.address);
    const client = sdk.createClient({
      chain: sdk.chains.studionet,
      account,
    });
    const txHash = await client.writeContract({
      address: contractAddr,
      functionName: 'register_artist',
      args,
    });
    console.log('tx hash:', txHash);
  } catch (e) {
    console.error('ERROR:', e.message);
    if (e.shortMessage) console.error('  short:', e.shortMessage);
    if (e.cause) console.error('  cause:', e.cause.message || e.cause);
    process.exit(1);
  }
})();
