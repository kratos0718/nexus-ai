"""
Evaluation endpoints — view and trigger RAG evaluation runs.

GET  /eval/results        list saved result files
GET  /eval/results/latest view the most recent result
GET  /eval/results/{name} view a specific result file
POST /eval/run            trigger an evaluation run (admin/dev only)
"""

import json
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_current_user
from app.models.user import User

router = APIRouter()

RESULTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "eval" / "results"


def _list_result_files() -> list[str]:
    if not RESULTS_DIR.exists():
        return []
    return sorted(
        [f.name for f in RESULTS_DIR.glob("eval_*.json")],
        reverse=True,
    )


def _load_result(filename: str) -> dict:
    path = RESULTS_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Result file '{filename}' not found.")
    # guard against path traversal
    try:
        path.resolve().relative_to(RESULTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    return json.loads(path.read_text())


@router.get("/results", summary="List all evaluation result files")
async def list_results(current_user: User = Depends(get_current_user)):
    files = _list_result_files()
    return {"count": len(files), "files": files}


@router.get("/results/latest", summary="View the most recent evaluation report")
async def get_latest_result(current_user: User = Depends(get_current_user)):
    files = _list_result_files()
    if not files:
        raise HTTPException(status_code=404, detail="No evaluation results found. Run the evaluator first.")
    return _load_result(files[0])


@router.get("/results/{filename}", summary="View a specific evaluation report by filename")
async def get_result(filename: str, current_user: User = Depends(get_current_user)):
    if not filename.startswith("eval_") or not filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Filename must match pattern eval_<timestamp>.json")
    return _load_result(filename)


@router.post("/run", summary="Trigger a custom-metrics-only evaluation run (no RAGAS)")
async def trigger_eval(current_user: User = Depends(get_current_user)):
    """
    Runs eval/runner.py --skip-ragas in a subprocess and returns the summary.
    RAGAS is excluded because it requires the full model stack and takes minutes.
    This endpoint is for quick sanity-check runs during development.
    """
    backend_dir = Path(__file__).parent.parent.parent.parent.parent
    try:
        result = subprocess.run(
            [sys.executable, "-m", "eval.runner", "--skip-ragas"],
            cwd=str(backend_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Evaluation timed out after 120 seconds.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start evaluation: {e}")

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Evaluation failed.\nstdout: {result.stdout}\nstderr: {result.stderr}",
        )

    # Load and return the just-written result
    files = _list_result_files()
    if not files:
        return {"status": "completed", "output": result.stdout}

    report = _load_result(files[0])
    summary = {
        "status": "completed",
        "report_file": files[0],
        "total_cases": report.get("total_cases"),
        "successful_cases": report.get("successful_cases"),
        "custom_metrics_avg": report.get("custom_metrics_avg"),
    }
    return summary
