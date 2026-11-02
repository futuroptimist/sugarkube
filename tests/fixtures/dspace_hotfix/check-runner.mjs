// Offline integration: execute the pinned upstream parser and proof/config validators.
// This deliberately does not launch Playwright or claim a browser journey.
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
const root = process.argv[2];
const input = JSON.parse(readFileSync(0, 'utf8'));
const runner = await import(pathToFileURL(resolve(root, 'scripts/run-remote-chat-smoke.mjs')));
const identity = await import(pathToFileURL(resolve(root, 'scripts/hotfix-302-contract.mjs')));
const provider = await import(pathToFileURL(resolve(root, 'frontend/e2e/remote-chat-smoke-contract.ts')));
try {
  const options = runner.parseAndValidateArgs(input.argv.slice(1), {});
  const proof = identity.validateHotfixRuntime(input.meta, input.health, options);
  provider.validateProviderConfig(input.config, options.providerConfigContract, options.expectedProvider);
  console.log(identity.artifactProofPrefix + JSON.stringify(proof));
} catch (error) {
  console.error(error.message);
  process.exitCode = 2;
}
