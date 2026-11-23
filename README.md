# llm-casino-harness

## Demo

"Can you beat the AI?" is a blackjack table for visitors. They play 3 deals, then see their first moves next to the Baseline and Full harness Seats (qwen2.5:7b, which played these exact hands earlier) and basic strategy.

1. Export the agents' answers from the two scenario runs into `demo/demo_data.json`:

   ```
   .venv/bin/python scripts/export_demo_data.py
   ```

   Deals the Full harness has not answered yet are left out of play. Re-run the export when `runs/mac_demo_scenarios_prob_strat_self` finishes; the server picks up the new file without a restart.

2. Start the server (Python standard library only):

   ```
   .venv/bin/python scripts/demo_server.py
   ```

3. Open http://localhost:8000. After about 30 seconds idle it falls back to the attract screen.

Presenter mode: press **Shift+Alt+P** (or open http://localhost:8000/#presenter). You pick deals from a search box or the strategy chart, play as many as you like, then press See results. Presenter hands are not posted to the live board.

Visitor results go to `demo/visitor_results.jsonl`, which git ignores. A browser check of the whole flow (needs Playwright and Chrome):

```
NODE_PATH=<node_modules with playwright> node tests/js/demo_e2e.js --out /tmp/demo-shots
```
