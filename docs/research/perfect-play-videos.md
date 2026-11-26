# Perfect Play (YouTube): Monopoly and Catan strategy-simulation videos, and how they built and compared player types

Researched 2026-11-25. Budget: hard (about 20), used 19 tool calls.

## Answer
**I confirmed the channel and both videos.** The channel is "Perfect Play", handle `@PerfectPlaySim` (https://www.youtube.com/@PerfectPlaySim). YouTube's oEmbed endpoint gives that author for the Catan video. Kottke and Neatorama credit the Monopoly video to Perfect Play and link the same channel.
- **Monopoly:** "The Best Monopoly Strategy, Tested on 300 Million Games" (https://www.youtube.com/watch?v=S_2eVAaw1UM, about October 2026).
- **Catan:** "The Best Catan Strategy, Tested on 200 Million Games" (https://www.youtube.com/watch?v=3XLDKvhrIjk, about early November 2026).
- **Risk:** the creator mentions an earlier Risk video, but I couldn't find it.

**How the players were built.** These are not LLM or RL agents, as far as the sources say. The creator "turned eight classic Monopoly strategies into computer players" and "the six plans people argue about [in Catan] into players". Each player is a scripted, rule-based habit. Each player was then measured by win rate over hundreds of millions of simulated games, against a 25% fair share at a four-player table. In Catan, the comparison was against "a regular player" baseline (one plan vs three regular players).

**Tuning step.** Monopoly had an extra step where "the computer tune[d] every habit at once". This looks like a parameter search, not opponent modelling.

**What I couldn't get.** YouTube pages, descriptions and transcripts did not load through my fetch tool. So I could not confirm:
- the exact pairing or seat-rotation scheme
- how the 312,898,560 count breaks down
- whether any code or repo exists
- whether any agent adapted to opponents

None of the sources I read describe opponent modelling.

## Findings
1. **The channel is "Perfect Play", handle @PerfectPlaySim.** (High)
   - https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=3XLDKvhrIjk&format=json
   - > `author_name`: "Perfect Play" / `author_url`: "https://www.youtube.com/@PerfectPlaySim"
   - https://www.neatorama.com/2026/10/20/The-Best-Monopoly-Strategy-as-Tested-on-300-Million-Games/
   - > "YouTuber Perfect Play runs simulations to determine the best strategies for playing board games."
   - The page links the channel at https://www.youtube.com/@PerfectPlaySim.

2. **The Monopoly video is "The Best Monopoly Strategy, Tested on 300 Million Games" (video ID S_2eVAaw1UM).** (High)
   - https://kottke.org/26/10/the-best-monopoly-strategy-tested-on-300-million-games (October 2026)
   - > "Perfect Play ran over 300 million games of Monopoly to determine the best strategy and the most common mistakes players make."
   - The title was also confirmed from the YouTube page header and oEmbed.

3. **The Monopoly player types were eight scripted "classic strategies" turned into computer players.** They played 312,898,560 games against each other at four-player tables. (High: the creator's words, quoted by Kottke)
   - https://kottke.org/26/10/the-best-monopoly-strategy-tested-on-300-million-games
   - > "I turned eight classic Monopoly strategies into computer players and made them play 312,898,560 games against each other."
   - > "At a table of four, the best one won 43% of its games."
   - > "The worst one won 3%."

4. **The Monopoly result: the spread between strategies comes from four habits, not one trick.** (High: the creator's words via Kottke)
   - https://kottke.org/26/10/the-best-monopoly-strategy-tested-on-300-million-games
   - > "The gap doesn't come from one clever trick."
   - > "It comes from four common mistakes: being picky about what you buy, saving your cash, stopping at three houses," "and refusing to trade."

5. **The best Monopoly strategy, "All In", is a fully scripted aggressive policy.** It buys everything, builds early, holds no cash, overbids to complete sets, and stays in jail late in the game. The worst strategy buys only railroads and utilities and never trades. (Medium: one secondary source)
   - https://www.neatorama.com/2026/10/20/The-Best-Monopoly-Strategy-as-Tested-on-300-Million-Games/ (2026-10-20)
   - > "The best strategy is what Perfect Play calls All In."
   - > "The All In player buys everything they land on and builds houses and hotels as soon as possible."
   - > "They never keep cash on hand, mortgaging properties as needed to build and to win auctions."
   - > "They will even pay up to three times the listed price to complete a set of properties if one of them goes to auction."
   - > "Late in the game, this player likes to stay in jail whenever possible."
   - > "The worst of these is to buying only railroads and utilities and never trading properties with other players."

6. **After the fixed strategies, the Monopoly video let "the computer" tune all habits at once.** This is an optimisation or parameter search over the scripted policy. The sources don't name the method. (Medium)
   - https://kottke.org/26/10/the-best-monopoly-strategy-tested-on-300-million-games
   - > "Then I let the computer tune every habit at once, to see how far a carefully tuned player can go"

7. **The Monopoly video flags non-terminating games as a measurement problem.** (Medium)
   - https://kottke.org/26/10/the-best-monopoly-strategy-tested-on-300-million-games
   - > "roughly one game in six never ends"
   - How those games were scored (draws or excluded) is unverified.

8. **The Catan video is "The Best Catan Strategy, Tested on 200 Million Games" (video ID 3XLDKvhrIjk) by Perfect Play.** (High)
   - https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=3XLDKvhrIjk&format=json
   - > `author_name`: "Perfect Play"
   - The title was confirmed from the YouTube page header.

9. **The Catan design: six popular "plans" became scripted players, each measured against a "regular player" baseline.** There were just over 200 million games, at four-player tables of one plan vs three regulars, so the fair share is 25%. (Medium: the creator's words, quoted in one secondary blog)
   - https://www.langweiledich.net/die-beste-catan-strategie/ (2026-11-07)
   - > "I turned the six plans people argue about into players," "added a regular player to compare them against," and "made them play a little over 200 million games."
   - > "Knight Army and All Five tied for first, both at 57% against three regular players (a fair share is 25%)."

10. **Catan results:**
    - Knight Army and All Five tied at 57%.
    - The port plan finished last at all 20 of its tables, which suggests 20 table configurations per plan.
    - "Settlements before cities" was the biggest single effect.

    (Medium)
    - https://www.langweiledich.net/die-beste-catan-strategie/
    - > "The port plan finished last at all 20 of its tables."
    - > "The biggest single thing I found is settlements before cities, at 5:55."
    - The meaning of the "20 tables" (board layouts? seat positions? opponent mixes?) is unverified.

11. **The channel also made an earlier Risk video.** (Medium)
    - https://www.langweiledich.net/die-beste-catan-strategie/
    - > "This one's for everyone who asked for Catan after the Risk video."

## Conflicts
- **Monopoly game count:** Kottke quotes exactly 312,898,560 games; the title says "300 Million". These agree, since the title rounds the number. A search summary of Moneywise said "more than 312 million", but I couldn't fetch that page (403).
- **A different Monopoly AI video:** A separate, older Monopoly AI video (b2studios, NEAT neuroevolution, about 11.2 million games) turns up in the same searches. It is NOT Perfect Play, so don't mix up their methods.

## Unverified
- **Seat and turn-order rotation, and the pairing scheme.** For Monopoly I couldn't confirm round robin of all 8 vs one-vs-three-baseline. For Catan I couldn't confirm what the "20 tables" are. Transcripts didn't load.
- **How variance and luck were handled,** beyond the sheer number of games. I found no mention of confidence intervals, mirrored dice, or duplicate seeds.
- **Any linked code, GitHub repo, website or paper.** A search for "PerfectPlaySim github" found nothing. A search snippet mentioned a "perfectplaysim" affiliate tag in the Catan description, but I couldn't confirm it.
- **The names and definitions of the other Monopoly strategies (6 of 8) and Catan plans (3 of 6).**
- **Whether any agent adapted to or modelled its opponents.** No source says so, and every described player is a fixed policy.
- **Moneywise's claim** (from a search snippet only) that liquidity-first players rarely won, and that orange is the recommended color group.
- **A Catan finding from the search snippet:** "reacting to the leader matters as much as always robbing the leader". It is not confirmed in a fetched page.

## Leads
- **Transcripts:** Fetch the transcripts of S_2eVAaw1UM and 3XLDKvhrIjk from a machine that can run `yt-dlp --write-auto-subs`. This should settle the seat rotation, the meaning of "20 tables", the non-ending games and the tuning method.
- **Risk video:** Find the Perfect Play Risk video on the channel page in a real browser.
- **Reaction video:** "The Best Catan Strategy, Tested on 200 Million Games - Catan Pro Reacts" (https://www.youtube.com/watch?v=5PTM5PdqyVw) may discuss the method.

## Sources read
- https://kottke.org/26/10/the-best-monopoly-strategy-tested-on-300-million-games (kottke.org, Oct 2026): the creator's own summary lines, the game count, win rates, four mistakes, tuning, and non-ending games.
- https://www.neatorama.com/2026/10/20/The-Best-Monopoly-Strategy-as-Tested-on-300-Million-Games/ (Neatorama, 2026-10-20): the All In and worst-strategy definitions, and the channel link.
- https://www.langweiledich.net/die-beste-catan-strategie/ (langweiledich.net, 2026-11-07): the creator's Catan summary, the baseline design, 57% results, 20 tables, and the Risk mention.
- https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=3XLDKvhrIjk&format=json (YouTube): the author name and handle for the Catan video.
- https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=S_2eVAaw1UM&format=json (YouTube): the Monopoly title and Perfect Play as author.
- https://www.youtube.com/watch?v=S_2eVAaw1UM, https://www.youtube.com/watch?v=3XLDKvhrIjk, https://www.youtube.com/watch?v=5PTM5PdqyVw, https://www.youtube.com/@PerfectPlaySim/videos (YouTube): only the titles loaded, with no descriptions or video lists.
- https://moneywise.com/life/entertainment/how-to-win-at-monopoly: returned 403, so I didn't use it.

## Lessons for our poker bot design
These are inferences (Low to Medium), drawn from the method Perfect Play appears to use.

1. **Define each opponent as one named, fixed, scripted habit with concrete rules.** Write them the way "All In" was written: buy everything, build ASAP, hold no cash, overbid up to 3x to complete a set. For poker:
   - **Calling station:** calls any bet up to X pot and never raises without the nuts.
   - **Maniac:** raises or 3-bets at frequency F with any two cards.
   - **Rock:** plays only the top N% of hands and folds to aggression without top pair.
   - **No-leak control:** a sound baseline policy.

   Make each habit a single parameter you can vary. Perfect Play's framing of "four common mistakes" is a dial-per-leak design. That maps directly onto measuring how much the LLM exploits each leak.
2. **Use a fixed reference baseline, like Catan's "regular player".** Report each matchup against the fair share, which is 50% heads-up or 0 bb/100. Your no-leak control plays the role of the "regular player". Score the LLM against each bot relative to its result against the control. That isolates exploitation from raw skill.
3. **Structure matches as many configurations ("tables"), not one long session.** Perfect Play reports results "at all 20 of its tables", and the meaning of those tables is unverified. Even so, the idea of a strategy holding up across 20 configurations applies to us. Heads-up, rotate the button every hand and split the sessions into seeds. Report per-seed results so you can say "won at k of N seeds", not just a pooled mean.
4. **Luck: Perfect Play's main tool appears to be brute volume** (200 to 300 million games). That is affordable for scripted bots but not for an LLM. You can't run millions of LLM hands, so use variance reduction instead:
   - **Duplicate poker:** play the same deck seeds with seats swapped.
   - **Fixed seed sets** shared across all opponent types.
   - **All-in EV adjustment.**
   - **Confidence intervals in bb/100.**

   Use bot-vs-bot runs, which are cheap, to fix each bot's baseline win rate with millions of hands, as Perfect Play did.
5. **Plan for degenerate or non-terminating outcomes up front.** Monopoly had "roughly one game in six never ends". Decide now how to score busted stacks, hand caps, or parse failures, so they don't silently bias win rates.
6. **Adaptation is your novel part.** None of the sources describe any Perfect Play agent modelling its opponents; every player is a fixed policy. An LLM with opponent memory is the contribution. A "memory off" ablation against the same scripted bots and seeds is the clean comparison.
