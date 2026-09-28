"""Command-line interface: `medagent search|new|trials|drug|ask|serve`."""

from __future__ import annotations

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from .evidence import design_label
from .harness import ResearchHarness
from .models import SearchFilters, StudyDesign

app = typer.Typer(help="MedAgent: medical research agent and evidence search.", no_args_is_help=True)
console = Console()

LOE_STYLE = {1: "bold green", 2: "bold blue", 3: "yellow", 4: "dark_orange", 5: "grey62"}


def _run(coro):
    return asyncio.run(coro)


def _articles_table(articles, title: str) -> Table:
    table = Table(title=title, show_lines=True, expand=True)
    table.add_column("#", justify="right", width=3)
    table.add_column("Evidence", width=18)
    table.add_column("Study", ratio=3)
    table.add_column("Year", width=6)
    table.add_column("n", justify="right", width=8)
    table.add_column("Conclusion", ratio=4)
    for i, a in enumerate(articles, 1):
        loe = f"[{LOE_STYLE[a.evidence_level]}]LoE {a.evidence_level}[/] {design_label(a.design)}"
        if a.is_preprint:
            loe += "\n[yellow]preprint[/]"
        if a.is_retracted:
            loe = "[bold red]RETRACTED[/]"
        ident = f"PMID {a.pmid}" if a.pmid else (a.doi or a.url or "")
        table.add_row(str(i), loe, f"[bold]{a.title}[/]\n[dim]{a.journal or ''} · {ident}[/]", str(a.year or ""),
                      f"{a.sample_size:,}" if a.sample_size else "", a.bottom_line or "")
    return table


@app.command()
def search(
    query: str,
    year_from: Optional[int] = typer.Option(None, "--from", help="Earliest publication year"),
    design: list[StudyDesign] = typer.Option([], "--design", "-d", help="Restrict to study designs (repeatable)"),
    oa: bool = typer.Option(False, "--oa", help="Free full text only"),
    limit: int = typer.Option(15, "--limit", "-n"),
):
    """Federated evidence search, ranked by level of evidence."""
    async def go():
        async with ResearchHarness() as h:
            return await h.search(query, SearchFilters(year_from=year_from, designs=design, open_access_only=oa, max_results=limit))

    bundle = _run(go())
    console.print(_articles_table(bundle.articles, f"Evidence for “{query}”"))
    if bundle.web:
        console.print(Panel("\n".join(f"• [bold]{w.title}[/] ({w.authority or w.site})\n  {w.url}" for w in bundle.web), title="Guidelines"))
    if bundle.trials:
        console.print(Panel("\n".join(f"• {t.nct_id} [{t.status}] {t.title}" for t in bundle.trials[:5]), title="Trials"))
    bad = [p for p in bundle.providers if not p.ok]
    if bad:
        console.print("[dim]Unavailable: " + "; ".join(f"{p.provider} ({p.error})" for p in bad) + "[/]")


@app.command()
def new(topic: str, days: int = typer.Option(30, "--days"), limit: int = typer.Option(20, "--limit", "-n")):
    """Newest papers and preprints on a topic."""
    async def go():
        async with ResearchHarness() as h:
            return await h.whats_new(topic, days=days, limit=limit)

    bundle = _run(go())
    console.print(_articles_table(bundle.articles, f"New in the last {days} days: “{topic}”"))


@app.command()
def trials(
    condition: str,
    intervention: Optional[str] = typer.Option(None, "--intervention", "-i"),
    location: Optional[str] = typer.Option(None, "--location", "-l"),
    recruiting: bool = typer.Option(True, "--recruiting/--all"),
    limit: int = typer.Option(15, "--limit", "-n"),
):
    """Search ClinicalTrials.gov."""
    async def go():
        async with ResearchHarness() as h:
            return await h.trials(condition=condition, intervention=intervention, location=location,
                                  recruiting_only=recruiting, limit=limit)

    table = Table(title=f"Trials: {condition}", expand=True)
    for col in ("NCT", "Status", "Phase", "n", "Title", "Sponsor"):
        table.add_column(col)
    for t in _run(go()):
        table.add_row(t.nct_id, t.status or "", "/".join(t.phases), str(t.enrollment or ""), t.title, t.sponsor or "")
    console.print(table)


@app.command()
def drug(name: str):
    """FDA label highlights and FAERS adverse-event signal for a drug."""
    async def go():
        async with ResearchHarness() as h:
            return await h.drug(name)

    label, events, _ = _run(go())
    if label:
        if label.boxed_warning:
            console.print(Panel(label.boxed_warning[:1500], title="BOXED WARNING", border_style="bold white"))
        for title, text in (("Indications", label.indications), ("Dosing", label.dosage), ("Contraindications", label.contraindications)):
            if text:
                console.print(Panel(text[:1200], title=title))
        if label.url:
            console.print(f"[dim]{label.url}[/]")
    else:
        console.print(f"No FDA label found for {name}.")
    if events and events.top_reactions:
        console.print(f"FAERS: {events.total_reports or 0:,} reports, {events.serious_reports or 0:,} serious. Top: "
                      + ", ".join(f"{r.term} ({r.count:,})" for r in events.top_reactions[:10]))


@app.command()
def ask(question: str, show_sources: bool = typer.Option(True, "--sources/--no-sources")):
    """Ask the research agent a clinical question (needs a model API key)."""
    from .agent import AgentService

    async def go():
        async with ResearchHarness() as h:
            service = AgentService(h)
            answer = ""
            sources = []
            with console.status("Researching…") as status:
                async for ev in service.stream(question):
                    if ev["type"] == "tool_start":
                        status.update(f"{ev['name']}: {str(ev['args'])[:80]}")
                        console.print(f"[dim]→ {ev['name']} {ev['args']}[/]")
                    elif ev["type"] == "sources":
                        sources.extend(ev["items"])
                    elif ev["type"] == "answer":
                        answer = ev["text"]
                    elif ev["type"] == "error":
                        raise typer.Exit(console.print(f"[red]{ev['message']}[/]") or 1)
            return answer, sources

    answer, sources = _run(go())
    console.print(Markdown(answer))
    if show_sources and sources:
        console.rule("Sources")
        for s in sources:
            r = s["record"]
            title = r.get("title") or (r.get("generic_names") or [""])[0]
            console.print(f"[{s['n']}] {title} — {r.get('url') or ''}")


@app.command()
def calc(name: Optional[str] = typer.Argument(None, help="Calculator name; omit to list them"),
         params: list[str] = typer.Argument(None, help="key=value inputs, e.g. age=72 sex=female hypertension=true")):
    """Run a validated clinical calculator: `medagent calc cha2ds2_vasc age=78 sex=female hypertension=true`."""
    from .ml import calculators

    if not name:
        table = Table(title="Clinical calculators")
        for col in ("Name", "Category", "Title"):
            table.add_column(col)
        for c in calculators.REGISTRY.values():
            table.add_row(c.name, c.category, c.title)
        console.print(table)
        return
    inputs = {}
    for item in params or []:
        key, _, raw = item.partition("=")
        low = raw.lower()
        inputs[key] = True if low == "true" else False if low == "false" else raw
        try:
            inputs[key] = float(raw) if "." in raw else int(raw)
        except ValueError:
            pass
    try:
        r = calculators.run(name, inputs)
    except calculators.CalculatorError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    console.print(Panel(f"[bold]{r.value:g} {r.unit or ''}[/] {('— ' + r.band) if r.band else ''}\n{r.interpretation}\n\n"
                        + "\n".join(f"[dim]• {c}[/]" for c in r.caveats), title=r.title, subtitle=calculators.REGISTRY[name].reference))


@app.command()
def skills(question: Optional[str] = typer.Argument(None, help="Show which skills a question would activate")):
    """List the agent's clinical skills, or route a question to them."""
    from .skills import SkillRegistry

    reg = SkillRegistry()
    if question:
        from .ml.nlp import ClinicalNLP

        labels = [e.label for e in ClinicalNLP().analyze(question).entities if not e.negated]
        for m in reg.route(question, labels):
            console.print(f"[bold]{m.skill.name}[/] score {m.score:g} ({', '.join(m.reasons)})")
        return
    for s in reg.skills.values():
        console.print(f"[bold]{s.name}[/] — {s.description}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
    """Run the web app (http://127.0.0.1:8000)."""
    import uvicorn

    uvicorn.run("medagent.server:app", host=host, port=port, reload=reload)


if __name__ == "__main__":  # pragma: no cover
    app()
