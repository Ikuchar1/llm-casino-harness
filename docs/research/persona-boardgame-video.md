# Which video had AI/LLM "player types" play Monopoly and Catan, how were the personas built, and what transfers to scripted poker opponents?

Researched 2026-11-25. Budget: hard, used 20 tool calls.

## Answer
**I did not find a single video that covers both Monopoly and Catan with designed personalities. Treat the identification as unconfirmed.** The closest candidates are three separate videos from 2025–2026. It is plausible the student is merging two of them:
- **Monopoly:** "I Made 5 AIs Play Monopoly" by Kept You Waiting (2026-10-02), or "GPT 5.2 vs Claude Opus 4.5 vs Grok 4.1 vs Gemini 3 Pro - AI Plays Monopoly" by JC BuenaVentura (2025-12-28).
- **Catan:** "I Made 12 AI Decision Models Play Catan to See Who's Best" by The Hype Kevin (2026-10-16).

In all three, the "personalities" are different models, not authored personas. The Monopoly videos are single games with one winner reported. The Catan video is a structured tournament (69 games, league plus playoffs plus a final against the classic Catan bots) with a public per-move log. None of the sources I read show agents keeping memory of, or explicitly modelling, a specific opponent.

The closest rigorous work on authored personas is the arXiv paper AgentMonopoly (Oct 2026). Its key finding is that persona prompts change what agents say more reliably than what they do, so it judges adherence by actions and outcomes.

## Findings
1. **Candidate A (Monopoly): Kept You Waiting, "I Made 5 AIs Play Monopoly", uploaded 2026-10-02, about 21.8k views. The "players" are five different LLMs, and one winner is reported.** (High for existence and metadata; Medium for content, which comes from the description only)
   - https://www.youtube.com/watch?v=ZTsDyNmOFEQ (oEmbed plus page metadata fetched)
   - > "Watch ChatGPT, Gemini, Claude, Grok, and DeepSeek battle for real estate supremacy."
   - > "I put five leading language models into a simulated game of Monopoly to see how they handle strategic trading, auctions, and bankruptcy."
   - > "Gemini emerges as the clear victor with a net worth of $3,898."
   - The channel's recent uploads (RSS) cover Level Devil, Squid Game, Bomberman and Mario. **No Catan video appears** in the roughly 15 most recent uploads, though I did not see the full back catalogue.

2. **Candidate B (Monopoly): JC BuenaVentura (@The_Ai_Vice), "GPT 5.2 vs Claude Opus 4.5 vs Grok 4.1 vs Gemini 3 Pro - AI Plays Monopoly", uploaded 2025-12-28, about 45.7k views. Four frontier models, a custom environment with modified rules, and chain-of-thought logging.** (High for metadata; Medium for content)
   - https://www.youtube.com/watch?v=_4NBhO1ez3k
   - > "I built a custom environment to find out. In this AI agent simulation, we aren't just watching the moves; we are logging their internal \"Chain of Thought\" to see exactly why they make their decisions."
   - The chapters label emergent styles, not authored ones: > "02:06 - Claude's Strategy: The Venture Capitalist \"Spray & Pray\"" and > "07:50 - Mid-Game Analysis: Slumlord vs. Billionaire vs. Overthinker"

3. **In Candidate B the full board state was given every turn, trash talk was prompted, and the single game ended with no clear winner because of an environment bug.** (Medium: the quotes are from a third-party transcript summary, readray.ai, not the video itself)
   - https://readray.ai/notes/pt/grok-41-20260205/gpt-claude-grok-gemini-monopoly-battle
   - > "Every turn, they receive the entire board state"
   - > "I explicitly encouraged them to trash talk each other in the chat"
   - > "we did not get a clear winner" ... "I didn't add the option for the AIS to sell houses"
   - The summary says the run was one game and that the creator refers to an earlier attempt.

4. **Candidate C (Catan): The Hype Kevin, "I Made 12 AI Decision Models Play Catan to See Who's Best", uploaded 2026-10-16. It ran 69 games in a tournament structure built on the open-source Catanatron engine.** (High; from the video description)
   - https://www.youtube.com/watch?v=b55Tdaumnt0
   - > "I made the 12 best AI decision models play Catan: a qualifier against random bots, a full league, playoffs, a best-of-three final, and a boss fight against the classic Catan bots. 69 games, and every move picked from odds."
   - > "Game engine: catanatron, the open-source Catan simulator (GPL-3.0): https://github.com/bcollazo/catanatron"
   - The channel's recent uploads are Claude Code and dev-tool videos. I saw no Monopoly video.

5. **Candidate C's "players" are non-generative decision models that score a list of legal options. Every decision, with its odds, time and cost, is logged publicly.** (High; companion site)
   - https://catan.thehypekevin.com
   - > "A decision model never writes text. Give it a situation and a list of options, and it returns odds for every option in one pass."
   - > "Watch tournament games and inspect the recorded choices, probabilities, time and cost of twelve decision models."
   - The site counter showed "Completed games 87", "Recorded decisions 59,636" and "Total spend · USD $3.44" with "TOURNAMENT IN PROGRESS". That is more than the 69 in the video, so the site was still accumulating games.

6. **AgentMonopoly (arXiv 2610.29330, Oct 2026) assigns authored personas to LLM Monopoly agents and finds that personas shift language more reliably than actions.** (High; primary paper abstract, but the fetch tool paraphrased the abstract)
   - https://arxiv.org/abs/2610.29330v2
   - The title is quoted verbatim: "AgentMonopoly: Behavioral Patterns and Persona Control in LLM Agents"; submitted 21 Oct 2026 (v1), revised 22 Oct 2026 (v2).
   - Paraphrase of the abstract, because the summarizer would not quote it in full:
     - One agent per game gets a persona meant to shift a tendency observed without it.
     - Personas change wording and some actions, but not consistently, so adherence should be judged by actions and outcomes.
     - The setup uses four model families at two sizes, with five seeds per configuration.
     - Larger models don't reliably win more.
   - A search snippet named the personas "Zen, Independent, Diplomatic, and Conservative" and said four-agent games were played on one modified board. That came from a snippet only (see Unverified).
   - Repo from the search results (not fetched): https://github.com/SuELS-Group/Agent_Monopoly

7. **A simple Monopoly bot study used an aggressive type, a cautious type and a random control. It found the ranking depends on table size.** (Low; anonymous, undated science-fair page)
   - https://www.all-science-fair-projects.com/project1044.html
   - > "Type A plays aggressively. Type B plays cautiously. A Random player serves as a control."
   - > "The computer plays 300 games across three sets of 100."
   - > "In three-player games, Type B wins the most."
   - The page also reports the two types winning about equally in two-player games.

## Conflicts
- **Catan game count:** the video description says "69 games" (https://www.youtube.com/watch?v=b55Tdaumnt0), and the companion site says "Completed games 87" (https://catan.thehypekevin.com). The likely reason is that the site kept running after the video was cut, since it shows "TOURNAMENT IN PROGRESS". That is inference, not confirmed.

## Unverified
- **AgentMonopoly persona names and board:** that the personas are "Zen, Independent, Diplomatic, and Conservative" and that the Conservative agent "keeps more cash while continuing to accept most offers". This came from a search snippet about the bytez.com mirror and was not in the fetched abstract.
- **Diplomacy:** that a programmer had ChatGPT, Gemini, Claude and others play Diplomacy on Twitch, with each model showing a distinct "personality" (xatakaon.com snippet). Not fetched, and it is Diplomacy, not Monopoly or Catan.
- **A two-game LLM Catan project:** a blog with LLM-vs-LLM full Catan games and a replay viewer, where "Gemini 3.5 Flash won both" games (backlist.sdan.io/by/radshaan). The fetch failed (DNS).
- **PyCatan persona play:** RL agents play Catan while speaking as characters (Miss Minutes, HAL 9000, Marvin, C-3PO), and "the talking and the playing never touch". Search snippet only.
- **Persona weights in poke-monopoly:** a browser Monopoly prototype with Greedy, Aggressive, Cautious and Opportunist personalities defined by risk, aggression, liquidity and loyalty weights (github.com/AokDesu/poke-monopoly PR #201). Snippet only.
- **The Catan video's narration:** I have no transcript, so I could not check whether any model adapted to specific opponents or what the "Confidently wrong" chapter shows.

## Leads
- **Ask the student.** If they remember authored personas (for example "the greedy one" or "the trader"), none of the three candidates match well. If they remember "different AIs", Kept You Waiting (Monopoly) and The Hype Kevin (Catan) are the most likely pair, both from October 2026.
- **AgentMonopoly is the most useful source for our design.** The paper and repo test persona adherence directly.
- **Agents of Change / HexMachina (arXiv 2506.04651).** Self-evolving LLM Catan agents on Catanatron, benchmarked against Catanatron's AlphaBeta bot. This is a model for "LLM vs scripted bots" evaluation.
- **Catanatron's built-in bots** (random, weighted-random, AlphaBeta) work as a fixed scripted-opponent ladder, analogous to our bot zoo.

## Sources read
- https://www.youtube.com/watch?v=ZTsDyNmOFEQ (Kept You Waiting, 2026-10-02): title, description, winner, model list.
- https://www.youtube.com/watch?v=_4NBhO1ez3k (JC BuenaVentura, 2025-12-28): title, description, chapters.
- https://readray.ai/notes/pt/grok-41-20260205/gpt-claude-grok-gemini-monopoly-battle (third-party transcript summary): setup quotes for Candidate B.
- https://www.youtube.com/watch?v=b55Tdaumnt0 (The Hype Kevin, 2026-10-16): tournament structure, 69 games, Catanatron.
- https://catan.thehypekevin.com (companion site, Oct 2026): decision-model definition, logged decisions, cost.
- YouTube RSS feeds for the three channels: no channel had both a Monopoly and a Catan video among its recent uploads.
- https://arxiv.org/abs/2610.29330v2 (arXiv, Oct 2026): AgentMonopoly persona-control abstract.
- https://www.all-science-fair-projects.com/project1044.html (undated): aggressive, cautious and random-control design with 300 games.

## Lessons for our poker bot design
1. **Scripted bots give us ground truth that persona prompts can't.**
   - AgentMonopoly found persona prompts change wording more reliably than actions (Finding 6). An LLM told to "be a calling station" might not actually call too much.
   - Our rule-based calling station, maniac and rock do exactly what they're defined to do, so any "memory helped" result can be traced to a known leak.
   - Keep them scripted, and log each bot's VPIP and aggression stats to show its habit really shows up. (VPIP, "voluntarily put money in pot", is the share of hands where a player chooses to put chips in.)
2. **Judge "the agent learned the habit" by actions, not by its chat.** We should measure exploitative actions directly, such as:
   - folding fewer bluff-catchers against the maniac
   - value-betting thinner against the station
   - stealing more against the rock

   We shouldn't rely on whether the agent's reasoning text says "this opponent is loose". This is the AgentMonopoly lesson applied to us (Low; my inference).
3. **A one-game demo is not evidence.** Both Monopoly videos read as single games, and one ended without a winner because of an environment bug (Finding 3).
   - Use many hands, fixed seeds, and duplicate or mirrored deals to cut card luck.
   - Before the real runs, test that the engine supports every legal action, since the Monopoly bug came from a missing "sell houses" option.
4. **Use a ladder and a control, like the Catan tournament and the science-fair study.**
   - The Catan video ran a qualifier against random bots, then a league, then a "boss fight" against the classic bots (Finding 4).
   - The science-fair study used a random control (Finding 7).
   - Our no-leak control bot plays the same role. Memory should help against the leaky bots and do nothing, or nothing harmful, against the control.
5. **Results depend on the matchup.** The aggressive-vs-cautious ranking flipped between two- and three-player tables (Finding 7). Report results per opponent type rather than pooling them into one average.
6. **Log every decision with its context.** The Catan project's public per-move record of options, odds, time and cost (Finding 5) makes failures like "confidently wrong" auditable. Logging each decision with the memory state the agent saw would let us show how memory changed specific choices.
7. **None of the candidates test opponent memory.** None of the videos I found had agents remember or model each other, so a controlled memory-on versus memory-off ablation against fixed-habit bots is a gap these projects leave open (Low; based on what I could read, with no transcripts).
