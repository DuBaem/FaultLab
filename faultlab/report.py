"""Write a self-contained results page that teammates can open without Docker."""

from html import escape


def display(value, digits=1):
    return "—" if value is None else f"{value:.{digits}f}"


def table(headers, rows):
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(x))}</td>" for x in row) + "</tr>" for row in rows)
    return f"<div class='scroll'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def write_report(path, overview, reports):
    style = """
    *{box-sizing:border-box}body{margin:0;background:#f3f5f4;color:#18343b;font:16px/1.45 system-ui,sans-serif}
    main{max-width:1120px;margin:auto;padding:32px 5vw 70px}header{background:#17363e;color:white;padding:25px 5vw}
    header div{max-width:1010px;margin:auto}h1{margin:0;font-size:2rem}h2{margin:28px 0 7px}
    p{margin:7px 0 14px}th,td{text-align:left;padding:9px 12px;border-bottom:1px solid #cbd8d7}
    th{background:#e4ecea}table{border-collapse:collapse;width:100%;background:white;font-size:.91rem}
    .scroll{overflow-x:auto}summary{cursor:pointer;font-weight:650;padding:12px 0}details{margin:14px 0}
    .bar{height:13px;background:#176f74;min-width:1px;display:inline-block;vertical-align:middle;margin:0 8px}
    .row{display:grid;grid-template-columns:120px 1fr;align-items:center;margin:4px 0}.chart{background:white;padding:14px}
    @media print{header{background:white;color:#18343b}details{break-inside:avoid}main{padding:8px}}
    """
    sections = ["<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' "
                "content='width=device-width,initial-scale=1'><title>FaultLab experiment results</title>",
                f"<style>{style}</style><header><div><h1>FaultLab experiment results</h1></div></header><main>",
                f"<p>{len(reports)} of {overview['requested_trials']} trials recorded · {escape(overview['status'])}</p>"]
    if overview.get("error"):
        sections.append(f"<p>{escape(overview['error'])}</p>")
    for action, data in overview.get("metrics", {}).items():
        sections.append(f"<h2>{escape(action)}</h2>")
        sections.append(table(["Mean absolute start error", "SD of trial mean HTTP times",
                               "Trials with failed requests / sampled trials", "Failures / timeouts"],
                              [[display(data["mean_absolute_start_error_ms"])+" ms",
                                display(data["mean_latency_stddev_between_trials_ms"])+" ms",
                                f"{data['trials_with_failures']} / {data['trials_with_observations']}",
                                f"{data['failures']} / {data['timeouts']}"]]))
    if overview["comparisons"]:
        sections.append("<h2>Repeated request outcomes</h2><p>Pairs use the same action and request position "
                        "inside its confirmed window. A dash means there were no matched original failures.</p>")
        sections.append(f"<p>Original run: {escape(overview['comparisons'][0]['original_run_id'])}</p>")
        sections.append(table(["Repeat run", "Matched / original / repeat", "Same outcome",
                               "Reproduced / matched original failures", "Reproduction"],
                              [[r["repeat_run_id"], f"{r['matched_requests']} / {r['original_requests']} / {r['repeat_requests']}",
                                r["matching_outcomes"], f"{r['reproduced_failures']} / {r['matched_original_failures']}",
                                display(r["failure_reproduction_percent"]) + ("%" if r["failure_reproduction_percent"] is not None else "")]
                               for r in overview["comparisons"]]))
    for index, report in enumerate(reports, 1):
        sections.append(f"<h2>Trial {index}</h2><p>{escape(report['run_id'])}</p>")
        rows, bars = [], [("Baseline", report["baseline"]["latency_ms"]["mean"])]
        for a in report["actions"]:
            obs = a["observed"]
            rows.append([a["action_id"], ", ".join(f"{k}={v}" for k,v in a["configured"].items()),
                         display(a["planned_start_seconds"],3), display(a["dispatch_seconds"],3),
                         display(a["observed_start_seconds"],3), display(a["observed_end_seconds"],3),
                         f"{obs['successful_requests']} / {obs['failed_requests']} / {obs['timeouts']}",
                         "Verified" if a["cleanup_verified"] else "Failed"])
            bars.append((a["fault_type"], obs["latency_ms"]["mean"]))
        bars.append(("Recovery", report["recovery"]["latency_ms"]["mean"]))
        baseline, recovery = report["baseline"], report["recovery"]
        sections.append(f"<p>Baseline: {baseline['successful_requests']} of {baseline['total_requests']} requests succeeded. "
                        f"Recovery probes: {recovery['successful_requests']} of {recovery['total_requests']} succeeded.</p>")
        sections.append(table(["Fault", "Configured", "Planned (s)", "Dispatched (s)", "Confirmed (s)",
                               "Cleaned (s)", "HTTP OK / failed / timed out", "Cleanup"], rows))
        sections.append("<p>Mean response time for successful requests (ms)</p><div class='chart'>")
        largest = max([1]+[v for _,v in bars if v is not None])
        for label, val in bars:
            width = 65*val/largest if val is not None else 0
            sections.append(f"<div class='row'><span>{escape(label)}</span><span>"
                            f"<i class='bar' style='width:{width:.2f}%'></i>{display(val)}</span></div>")
        sections.append("</div><details><summary>Request timeline and outcomes</summary>")
        sections.append(table(["Request", "Started (UTC)", "Finished (UTC)", "Phase", "Action", "Outcome", "HTTP time (ms)"],
                              [[r["request_id"], r["started_at"], r["finished_at"], r["phase"], r["action_id"] or "—",
                                "OK" if r["success"] else ("Timeout" if r["timed_out"] else "Failed"),
                                display(r["latency_ms"])] for r in report["observations"]]))
        sections.append("</details>")
    sections.append("</main></html>")
    path.write_text("\n".join(sections), encoding="utf-8")
