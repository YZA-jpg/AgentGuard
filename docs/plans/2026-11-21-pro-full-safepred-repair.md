# Pro full baseline and SafePred SafetyDrift completion

User explicitly authorized both launches on 2026-11-21.

1. Use the completed Flash **author-lock full** batch as the control: model-only replacement, same 97 benign + 35 capability + 949 attack cases, four API workers, temperature=0, thinking/provider omitted, output cap omitted, DeepSeek attack addressee, system role and author limits unchanged. Do not substitute the different 939-case external-reference protocol or thinking-enabled 40-case diagnostic.
2. Before real API calls, verify historical plan/config, exact official install, system/tool hashes and all model-rendered injection inputs. Start an independent eight-case smoke (four benign + four attacked); verify it, then run the full1081 group and its offline checker. Save every native trace and API request/response.
3. Change only SafePred's formal SafetyDrift split name from `test` to `heldout`. Add a regression test, run native-core tests, and read-only verify all72 IDs and 38/34 labels against the existing manifest.
4. Preserve the ATBench200 result and the exact existing frozen SafetyDrift policy/model/sampling. Start only SafetyDrift72 in a new directory, with an independently verified summary at completion.
5. Use one memory-sufficient A100 for SafePred (batch1, sequential per-trajectory state). Pro's four API processes run concurrently without local GPU use. All paths/caches remain on data1. Save parameters and startup evidence; back up source/docs to GitHub.

Credential handling: obtain only allowlisted experiment fields from result metadata. Do not print server environment/session files or API keys. Current API endpoint is loaded by the existing native runner, with its sanitized provenance recording.
