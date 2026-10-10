# Voiceover Skill: प्लेटफ़ॉर्म संगतता

**सार:** एक साझा source package—`SKILL.md`, संदर्भ सामग्री और वैकल्पिक `scripts/`—को portable आधार की तरह रखा जा सकता है; Agent Skills standard इस directory संरचना को परिभाषित करता है।[19] लेकिन native import, packaging/discovery, अनुमति और bundled script का स्थानीय execution प्रत्येक host का अलग व्यवहार है; एक ही package को सभी जगह native रूप से install/run होने वाला न मानें।[1][6][11][15][18][19]

## प्लेटफ़ॉर्म स्थिति

| प्लेटफ़ॉर्म | सत्यापित native import और script execution | उपयुक्त adapter और सीमाएँ |
|---|---|---|
| **Claude Code** | Native `SKILL.md`-आधारित discovery: project में `.claude/skills/<name>/` या user scope में `~/.claude/skills/<name>/`; supporting files/scripts साथ रखे जा सकते हैं। Skill निर्देश Claude Code से script चलवा सकते हैं, पर install अपने-आप code नहीं चलाता।[1] | Portable core में relative script paths और स्पष्ट interpreter/dependencies दें; Claude Code-विशिष्ट निर्देश में `${CLAUDE_SKILL_DIR}` इस्तेमाल किया जा सकता है। Shell/filesystem access permissions, session mode, sandbox और host environment पर निर्भर है।[1][2][3] Claude Desktop का ZIP/Skills UI और API Skills का uploaded, isolated code-execution container अलग surfaces हैं—इन्हें local CLI import या local execution न समझें।[4][5] |
| **MiniMax M3 via MiniMax Code / MiniMax Agent Plugin** | **M3 एक मॉडल है, अलग Skill host नहीं।** MiniMax का आधिकारिक M3 पृष्ठ coding/agentic tool invocation बताता है; Skill का host MiniMax Code/Desktop या MiniMax Agent/Cloud Plugin surface है। Plugin package के root में `.minimax-plugin/plugin.json`, `skills/<name>/SKILL.md` और referenced files/scripts होते हैं। Official submission flow ZIP/GitHub source स्वीकार करता है और review/publishing प्रक्रिया बताता है.[6][7][20][21] | इस project के लिए MiniMax plugin-format adapter package बनाया जा सकता है; scripts को explicit interpreter और relative paths से चलाना होता है, install स्वयं scripts नहीं चलाता। Plugin docs desktop/cloud delivery target देते हैं, लेकिन raw M3 API अपने-आप SKILL import या local filesystem execution नहीं देती। M3 API पर text-generation integration अलग रहेगी; model weights local package में bundle/run नहीं होंगे.[6][20][21][22] |
| **Gemini CLI** | Native Agent Skills: workspace में `.gemini/skills/<name>/` या `.agents/skills/<name>/`; `gemini skills link/install` से workspace scope चुना जा सकता है। `SKILL.md` में bundled scripts का उल्लेख कर CLI shell tool से चलवाया जा सकता है।[11][12] | Portable directory, स्पष्ट `python3` invocation और dependency निर्देश रखें। Skill activation consent, workspace trust और shell-tool approvals लागू होते हैं; sandbox में default workspace access है, बाहर के paths के लिए अतिरिक्त अनुमति/mount लग सकता है।[11][12][13] Gemini API/Managed Agents में CLI-जैसा SKILL.md importer इन findings से स्थापित नहीं है।[14] |
| **GroqCloud API** | जाँचे गए आधिकारिक API दस्तावेज़ों में native `SKILL.md` import, skill registry या bundled backend install path स्थापित नहीं है। Function calling में model tool-call देता है और caller का application code function चलाकर परिणाम लौटाता है।[15][16] | Skill files/backend अपने agent host में रखें; Groq model adapter को schema, validated arguments और allowlisted function dispatch दें, या backend को भरोसेमंद MCP server के रूप में expose करें।[15][16] Groq `code_interpreter` अलग ephemeral Python sandbox है; यह uploaded skill bundle/local filesystem runner नहीं है।[17] |
| **Cue** | Cue app में GitHub से Skill import करने का UI path उपलब्ध है: phone पर Settings → Skills → Add Skills → Import from GitHub; desktop पर Settings → Skills → Add → Import from GitHub (Cue app UI, checked 2026-10-10). Public materials still do not establish bundled Python/shell execution for this package. | यह import Skill instructions को उपलब्ध करा सकता है, लेकिन Cue में इस repository के backend की local Python execution या end-to-end TTS सत्यापित नहीं है। इसे verified local-runtime installation न बताएं; पहले host execution support verify करें। |

### MiniMax M3 की सही सीमा

MiniMax M3 को इस project में **host compatibility** नहीं, बल्कि MiniMax Code/Agent के पीछे चुने जा सकने वाले **model target** के रूप में दर्ज किया गया है। Native Skill import/distribution का contract MiniMax Plugin format से आता है; केवल M3 API endpoint को call करने से स्थानीय voiceover scripts नहीं चलतीं। M3 के लगभग 428B parameters (लगभग 23B active) बताए गए हैं, इसलिए इस package में M3 weights या API credential शामिल नहीं होंगे। Agent को profile-backed voiceover backend तभी चलाना चाहिए जब चुने गए MiniMax Plugin runtime में packaged Python scripts और आवश्यक local files चलाने की अनुमति हो.[20][21][22]

## References

1. [Extend Claude with skills — Claude Code Docs](https://docs.anthropic.com/en/docs/claude-code/skills)
2. [Configure permissions — Claude Code Docs](https://docs.anthropic.com/en/docs/claude-code/permissions)
3. [Security — Claude Code Docs](https://docs.anthropic.com/en/docs/claude-code/security)
4. [Using Agent Skills with the API — Claude Platform Docs](https://docs.anthropic.com/en/build-with-claude/skills-guide)
5. [How to create custom skills — Claude Help Center](https://support.anthropic.com/en/articles/12512198-how-to-create-custom-skills)
6. [MiniMax Code: Plugin Development and Submission Guide](https://agent.minimax.io/docs/code/agents/plugin-submission)
7. [MiniMax Code: Plugin Marketplace](https://agent.minimax.io/docs/code/agents/plugins)
8. [MiniMax Agent Changelog](https://agent.minimax.io/docs/changelog)
9. [MiniMax Code CLI: Features and configuration](https://agent.minimax.io/docs/cli/features)
10. [MiniMax API: Text Chat](https://platform.minimax.io/docs/api-reference/text-chat)
11. [Agent Skills — Gemini CLI Documentation](https://geminicli.com/docs/cli/skills/)
12. [Get started with Agent Skills — Gemini CLI Documentation](https://geminicli.com/docs/cli/tutorials/skills-getting-started/)
13. [Sandboxing in Gemini CLI — Gemini CLI Documentation](https://geminicli.com/docs/cli/sandbox/)
14. [Gemini API — Google AI for Developers](https://ai.google.dev/gemini-api/docs)
15. [Local Tool Calling — GroqDocs](https://console.groq.com/docs/tool-use/local-tool-calling)
16. [Remote Tools and MCP — GroqDocs](https://console.groq.com/docs/tool-use/remote-mcp)
17. [Code Execution — GroqDocs](https://console.groq.com/docs/tool-use/built-in-tools/code-execution)
18. [Cue official website](https://cue.im/)
19. [Agent Skills Specification](https://agentskills.io/specification)
20. [MiniMax M3 — Official model page](https://www.minimax.io/models/text/m3)
21. [MiniMax API — Text generation and M3 access](https://platform.minimax.io/docs/guides/text-generation)
22. [MiniMax M3 — Official GitHub repository](https://github.com/MiniMax-AI/MiniMax-M3)


## MiniMax package layouts (verified 2026-10-10)

The builder emits separate standalone Skill, Claude Code Plugin, MiniMax Code dual-layout, and MiniMax Marketplace submission ZIPs. Keep the two MiniMax archives separate: the official submission guide says packages in another plugin format must first be converted to its native format, while MiniMax Code 0.3.x/0.4.0+ requires the parallel manifests below.

| Target | Required layout | Important detail |
|---|---|---|
| Agent Plugins 1.0 / MiniMax Code 0.3.x | Root `plugin.json` plus `skills/voiceover-skill/SKILL.md` | The root manifest uses the Agent Plugins 1.0 schema. MiniMax Code discovers immediate Skill directories and checks that each frontmatter `name` matches its directory. |
| MiniMax Code 0.4.0+ | `.claude-plugin/plugin.json`, top-level `skills/SKILL.md`, and byte-identical `skills/voiceover-skill/SKILL.md` | The manifest's `skills` path is `./skills/SKILL.md`. Include both Skill files for runtime and older validator compatibility. |
| MiniMax marketplace submission | `.minimax-plugin/plugin.json` directly at ZIP root, plus `skills/voiceover-skill/SKILL.md` | No wrapper directory. The manifest references the nested Skill; unused `apps` and `mcpServers` must be empty arrays. The submission surface is separate from the Code 0.3/0.4 compatibility manifest. |
| Claude Code Plugin | `.claude-plugin/plugin.json` and `skills/voiceover-skill/SKILL.md` | Claude Code's `skills` field names a directory, so its manifest uses `./skills/voiceover-skill`. Use the separately generated Claude ZIP, not the MiniMax 0.4 compatibility ZIP. |

Both MiniMax packages use an explicit Python interpreter for scripts and include only ASCII file paths; neither includes model weights, secrets, symlinks, lifecycle installers, Hooks, MCP servers, or native binaries. Only the Marketplace ZIP carries the MiniMax submission icon and example queries; its manifest points to the nested Skill, while the Code ZIP carries only the 0.3.x and 0.4.0+ compatibility manifests. Neither is a hosted service or a one-click runtime installer. The standalone Skill ZIP is appropriate for Agent Skills hosts whose discovery contract accepts a directory containing `SKILL.md`; always follow the target host's documented import and local-shell permissions.

Official references: [MiniMax Code Plugin compatibility layouts](https://raw.githubusercontent.com/MiniMax-AI/MiniMax-Code-Plugins/main/docs/plugin-compatibility.md), [MiniMax Agent Plugin submission guide](https://agent.minimax.io/docs/code/agents/plugin-submission), [Agent Plugins 1.0 manifest schema](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json), and [Claude Code plugin manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference).
