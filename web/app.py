from pathlib import Path

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette import status

from app.database import create_artwork as create_artwork_with_workspace
from web.db import (
    archive_artwork,
    archive_collection,
    create_collection,
    get_artwork,
    get_artwork_file_assignments,
    get_artwork_production,
    get_collection,
    get_dashboard,
    restore_artwork,
    search_artworks,
    update_artwork,
    update_artwork_production,
    update_collection,
    upsert_artwork_file,
)
from web.file_intake import save_uploaded_file
from web.production import (
    build_production_summary,
    list_workspace_files,
)
from web.ratio_generator import (
    generate_ratio_output,
    resolve_assigned_file,
)
from web.workspace import (
    inspect_workspace,
    open_workspace,
    refresh_workspace,
)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="ShangooliOS")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _artwork_context(artwork_code: str, **extra):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    production = get_artwork_production(artwork_code)
    files = list_workspace_files(artwork)
    assignments = get_artwork_file_assignments(artwork_code)

    production_summary = build_production_summary(
        artwork,
        production,
        files,
        assignments,
    )

    context = {
        "artwork": artwork,
        "workspace": inspect_workspace(artwork),
        "production": production,
        "workspace_files": files,
        "file_assignments": assignments,
        "production_summary": production_summary,
        "workflow": production_summary["workflow"],
    }
    context.update(extra)
    return context


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=get_dashboard(),
    )


@app.get("/search")
def search_page(
    request: Request,
    q: str = Query("", max_length=100),
):
    query = q.strip()

    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "query": query,
            "results": search_artworks(query) if query else [],
        },
    )


@app.get("/collections/new")
def new_collection_form(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="new_collection.html",
        context={},
    )


@app.post("/collections/new")
def create_collection_post(
    code: str = Form(...),
    name: str = Form(...),
    target_artwork_count: int = Form(0),
    collection_status: str = Form("planned"),
):
    collection_code = create_collection(
        code=code,
        name=name,
        target_artwork_count=target_artwork_count,
        status=collection_status,
    )

    return RedirectResponse(
        url=f"/collections/{collection_code}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/collections/{collection_code}")
def collection_page(request: Request, collection_code: str):
    collection, artworks, archived_artworks = get_collection(collection_code)

    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    return templates.TemplateResponse(
        request=request,
        name="collection.html",
        context={
            "collection": collection,
            "artworks": artworks,
            "archived_artworks": archived_artworks,
        },
    )


@app.get("/collections/{collection_code}/edit")
def edit_collection_form(request: Request, collection_code: str):
    collection, _, _ = get_collection(collection_code)

    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    return templates.TemplateResponse(
        request=request,
        name="edit_collection.html",
        context={"collection": collection},
    )


@app.post("/collections/{collection_code}/edit")
def edit_collection_post(
    collection_code: str,
    name: str = Form(...),
    target_artwork_count: int = Form(0),
    collection_status: str = Form(...),
):
    update_collection(
        collection_code=collection_code,
        name=name,
        target_artwork_count=target_artwork_count,
        status=collection_status,
    )

    return RedirectResponse(
        url=f"/collections/{collection_code.upper()}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/collections/{collection_code}/archive")
def archive_collection_post(collection_code: str):
    archive_collection(collection_code)

    return RedirectResponse(
        url="/",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/collections/{collection_code}/new")
def new_artwork_form(request: Request, collection_code: str):
    collection, _, _ = get_collection(collection_code)

    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    return templates.TemplateResponse(
        request=request,
        name="new_artwork.html",
        context={"collection": collection},
    )


@app.post("/collections/{collection_code}/new")
def create_artwork_post(
    collection_code: str,
    public_title: str = Form(...),
    working_title: str = Form(""),
    theme: str = Form(""),
):
    result = create_artwork_with_workspace(
        collection_code=collection_code,
        public_title=public_title,
        working_title=working_title,
        theme=theme,
    )

    return RedirectResponse(
        url=f"/artworks/{result['artwork_code']}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/artworks/{artwork_code}")
def artwork_page(request: Request, artwork_code: str):
    return templates.TemplateResponse(
        request=request,
        name="artwork.html",
        context=_artwork_context(
            artwork_code,
            workflow_error=request.query_params.get("workflow_error"),
        ),
    )


@app.post("/artworks/{artwork_code}")
def save_artwork(
    request: Request,
    artwork_code: str,
    public_title: str = Form(...),
    working_title: str = Form(""),
    theme: str = Form(""),
    story: str = Form(""),
    status_value: str = Form(..., alias="status"),
):
    normalized_status = status_value.strip().lower()

    if normalized_status == "listed":
        context = _artwork_context(artwork_code)
        workflow = context["workflow"]
        current_step = workflow.current_step

        listing_is_ready = (
            current_step is None
            or current_step["key"] == "published"
        )

        if not listing_is_ready:
            missing_steps = [
                step["label"]
                for step in workflow.steps
                if not step["complete"]
                and step["key"] != "published"
            ]

            missing_text = ", ".join(missing_steps)

            from urllib.parse import urlencode

            message = (
                "This artwork cannot be marked Listed yet. "
                f"Complete: {missing_text}."
            )

            query_string = urlencode({"workflow_error": message})

            return RedirectResponse(
                url=(
                    f"/artworks/{artwork_code.upper()}"
                    f"?{query_string}"
                ),
                status_code=status.HTTP_303_SEE_OTHER,
            )

    update_artwork(
        artwork_code=artwork_code,
        public_title=public_title,
        working_title=working_title,
        theme=theme,
        story=story,
        status=normalized_status,
    )

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/production")
def save_artwork_production(
    artwork_code: str,
    orientation: str = Form(""),
    master_ratio: str = Form(""),
    required_ratios: str = Form(""),
    original_approved: bool = Form(False),
    print_master_ready: bool = Form(False),
    ratio_exports_ready: bool = Form(False),
    mockups_ready: bool = Form(False),
    listing_content_ready: bool = Form(False),
    production_notes: str = Form(""),
):
    update_artwork_production(
        artwork_code=artwork_code,
        orientation=orientation,
        master_ratio=master_ratio,
        required_ratios=required_ratios,
        original_approved=original_approved,
        print_master_ready=print_master_ready,
        ratio_exports_ready=ratio_exports_ready,
        mockups_ready=mockups_ready,
        listing_content_ready=listing_content_ready,
        notes=production_notes,
    )

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?production_saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/files/source")
def upload_source_file(
    artwork_code: str,
    upload: UploadFile = File(...),
):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    try:
        saved = save_uploaded_file(
            artwork=artwork,
            upload=upload,
            role="source",
        )
        upsert_artwork_file(
            artwork_code=artwork_code,
            **saved,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        upload.file.close()

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?file_saved=source",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/files/print-master")
def upload_print_master(
    artwork_code: str,
    upload: UploadFile = File(...),
):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    try:
        saved = save_uploaded_file(
            artwork=artwork,
            upload=upload,
            role="print_master",
        )
        upsert_artwork_file(
            artwork_code=artwork_code,
            **saved,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        upload.file.close()

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?file_saved=master",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/files/ratio")
def upload_ratio_output(
    artwork_code: str,
    ratio: str = Form(...),
    upload: UploadFile = File(...),
):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    try:
        saved = save_uploaded_file(
            artwork=artwork,
            upload=upload,
            role="ratio_output",
            ratio=ratio,
        )
        upsert_artwork_file(
            artwork_code=artwork_code,
            **saved,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        upload.file.close()

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?file_saved=ratio",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/ratios/generate")
def generate_ratio_files(
    request: Request,
    artwork_code: str,
    generation_mode: str = Form("fit"),
    overwrite_existing: bool = Form(False),
):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    production = get_artwork_production(artwork_code)
    assignments = get_artwork_file_assignments(artwork_code)
    assignment_map = {row["role"]: row for row in assignments}

    try:
        source_path = resolve_assigned_file(
            artwork,
            assignment_map.get("print_master"),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    ratios = [
        value.strip()
        for value in (production["required_ratios"] or "").split(",")
        if value.strip()
    ]

    if not ratios:
        raise HTTPException(
            status_code=400,
            detail="No required ratios are defined",
        )

    results = []

    for ratio in ratios:
        result = generate_ratio_output(
            artwork=artwork,
            source_path=source_path,
            ratio=ratio,
            mode=generation_mode,
            overwrite=overwrite_existing,
        )
        results.append(result)

        if result["status"] in {"created", "skipped"}:
            upsert_artwork_file(
                artwork_code=artwork_code,
                role=f"ratio:{ratio}",
                relative_path=result["relative_path"],
                stored_filename=result["stored_filename"],
                original_filename=result["stored_filename"],
            )

    return templates.TemplateResponse(
        request=request,
        name="artwork.html",
        context=_artwork_context(
            artwork_code,
            ratio_generation_results=results,
        ),
    )


@app.post("/artworks/{artwork_code}/validate")
def validate_artwork_production(artwork_code: str):
    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?validated=1#validation",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/workspace/refresh")
def refresh_artwork_workspace(artwork_code: str):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    refresh_workspace(artwork)

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?workspace_refreshed=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/workspace/open")
def open_artwork_workspace(artwork_code: str):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    try:
        open_workspace(artwork)
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/archive")
def archive_artwork_post(artwork_code: str):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    archive_artwork(artwork_code)

    return RedirectResponse(
        url=f"/collections/{artwork['collection_code']}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/restore")
def restore_artwork_post(artwork_code: str):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    restore_artwork(artwork_code)

    return RedirectResponse(
        url=f"/collections/{artwork['collection_code']}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
