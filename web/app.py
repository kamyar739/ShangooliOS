from pathlib import Path
import shutil

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette import status

from app.database import (
    create_artwork as create_artwork_with_workspace,
    get_artwork_folder,
)
from web.db import (
    archive_artwork,
    archive_collection,
    create_collection,
    get_artwork,
    get_artwork_file_assignments,
    get_artwork_mockup_order,
    get_artwork_intelligence,
    get_artwork_listing_content,
    get_artwork_production,
    get_collection,
    get_dashboard,
    restore_artwork,
    save_artwork_mockup_order,
    search_artworks,
    set_artwork_production_flags,
    update_artwork,
    update_artwork_intelligence,
    update_artwork_listing_content,
    update_artwork_production,
    update_collection,
    upsert_artwork_file,
)
from web.file_intake import save_uploaded_file
from web.artwork_intelligence import analyze_artwork
from web.listing_writer import generate_listing_content
from web.mockup_generator import GENERATED_SLOTS, generate_listing_image, generate_mockups
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


def _generate_required_ratios(artwork, *, overwrite: bool) -> list[dict]:
    """Generate every configured ratio from the assigned print master."""
    artwork_code = artwork["artwork_code"]
    production = get_artwork_production(artwork_code)
    assignments = get_artwork_file_assignments(artwork_code)
    assignment_map = {row["role"]: row for row in assignments}
    source_path = resolve_assigned_file(
        artwork,
        assignment_map.get("print_master"),
    )
    ratios = [
        value.strip()
        for value in (production["required_ratios"] or "").split(",")
        if value.strip()
    ]

    results = []
    for ratio in ratios:
        result = generate_ratio_output(
            artwork=artwork,
            source_path=source_path,
            ratio=ratio,
            mode="fit",
            overwrite=overwrite,
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

    # A new master requires a fresh visual approval, even when generation succeeds.
    set_artwork_production_flags(
        artwork_code,
        ratio_exports_ready=False,
    )
    return results


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

    saved_order = {
        row["slot_key"]: row["position"]
        for row in get_artwork_mockup_order(artwork_code)
    }
    for item in production_summary["mockup_status"]:
        item["position"] = saved_order.get(
            item["slot_key"], item["default_position"]
        )
    production_summary["mockup_status"].sort(
        key=lambda item: item["position"]
    )

    context = {
        "artwork": artwork,
        "workspace": inspect_workspace(artwork),
        "production": production,
        "workspace_files": files,
        "file_assignments": assignments,
        "production_summary": production_summary,
        "workflow": production_summary["workflow"],
        "artwork_intelligence": get_artwork_intelligence(artwork_code),
        "listing_content": get_artwork_listing_content(artwork_code),
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


@app.post("/artworks/{artwork_code}/intelligence/analyze")
def analyze_artwork_post(artwork_code: str):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    assignments = {row["role"]: row for row in get_artwork_file_assignments(artwork_code)}
    source = None
    if assignments.get("source") is not None:
        try:
            source = resolve_assigned_file(artwork, assignments.get("source"))
        except ValueError:
            source = None
    result = analyze_artwork(artwork, source)
    update_artwork_intelligence(artwork_code, **result)
    return RedirectResponse(url=f"/artworks/{artwork_code}#artwork-intelligence", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/artworks/{artwork_code}/intelligence")
def save_artwork_intelligence_post(
    artwork_code: str,
    theme: str = Form(""), style: str = Form(""), mood: str = Form(""),
    primary_colors: str = Form(""), suggested_room: str = Form(""),
    target_customer: str = Form(""), generation_prompt: str = Form(""),
    negative_prompt: str = Form(""), ai_model: str = Form(""),
    analysis_notes: str = Form(""),
):
    update_artwork_intelligence(
        artwork_code, theme=theme.strip(), style=style.strip(), mood=mood.strip(),
        primary_colors=primary_colors.strip(), suggested_room=suggested_room.strip(),
        target_customer=target_customer.strip(), generation_prompt=generation_prompt.strip(),
        negative_prompt=negative_prompt.strip(), ai_model=ai_model.strip(),
        analysis_notes=analysis_notes.strip(),
    )
    return RedirectResponse(url=f"/artworks/{artwork_code}#artwork-intelligence", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/artworks/{artwork_code}/listing-content/generate")
def generate_listing_content_post(artwork_code: str):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    intelligence = get_artwork_intelligence(artwork_code)
    result = generate_listing_content(artwork, intelligence)
    update_artwork_listing_content(artwork_code, **result)
    set_artwork_production_flags(artwork_code, listing_content_ready=True)
    return RedirectResponse(
        url=f"/artworks/{artwork_code}#story-seo-writer",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/listing-content")
def save_listing_content_post(
    artwork_code: str,
    short_story: str = Form(""),
    long_story: str = Form(""),
    etsy_title: str = Form(""),
    etsy_description: str = Form(""),
    etsy_tags: str = Form(""),
    alt_text: str = Form(""),
    keywords: str = Form(""),
):
    values = {
        "short_story": short_story.strip(),
        "long_story": long_story.strip(),
        "etsy_title": etsy_title.strip(),
        "etsy_description": etsy_description.strip(),
        "etsy_tags": etsy_tags.strip(),
        "alt_text": alt_text.strip(),
        "keywords": keywords.strip(),
    }
    update_artwork_listing_content(artwork_code, **values)
    required_ready = all(values[key] for key in ("etsy_title", "etsy_description", "etsy_tags", "alt_text"))
    set_artwork_production_flags(artwork_code, listing_content_ready=required_ready)
    return RedirectResponse(
        url=f"/artworks/{artwork_code}#story-seo-writer",
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
    use_as_master: bool = Form(False),
):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    get_artwork_production(artwork_code)

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

        if use_as_master:
            workspace = get_artwork_folder(artwork)
            source_path = workspace / saved["relative_path"]
            master_folder = workspace / "02 Print Files"
            master_folder.mkdir(parents=True, exist_ok=True)
            master_filename = (
                f"{artwork['artwork_code']}_master{source_path.suffix.lower()}"
            )
            master_path = master_folder / master_filename
            shutil.copy2(source_path, master_path)
            upsert_artwork_file(
                artwork_code=artwork_code,
                role="print_master",
                relative_path=str(master_path.relative_to(workspace)),
                stored_filename=master_filename,
                original_filename=saved["original_filename"],
            )
            set_artwork_production_flags(
                artwork_code,
                print_master_ready=True,
            )
            _generate_required_ratios(artwork, overwrite=True)
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

    get_artwork_production(artwork_code)

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
        set_artwork_production_flags(
            artwork_code,
            print_master_ready=True,
        )
        _generate_required_ratios(artwork, overwrite=True)
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
    overwrite_existing: bool = Form(False),
):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    try:
        results = _generate_required_ratios(
            artwork,
            overwrite=overwrite_existing,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return templates.TemplateResponse(
        request=request,
        name="artwork.html",
        context=_artwork_context(
            artwork_code,
            ratio_generation_results=results,
        ),
    )



@app.post("/artworks/{artwork_code}/mockups/generate")
def generate_mockups_post(artwork_code: str):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    assignments = {
        row["role"]: row
        for row in get_artwork_file_assignments(artwork_code)
    }
    source_assignment = assignments.get("print_master") or assignments.get("source")
    if source_assignment is None:
        raise HTTPException(
            status_code=400,
            detail="Upload an artwork file before generating mockups",
        )

    try:
        source_path = resolve_assigned_file(artwork, source_assignment)
        workspace = get_artwork_folder(artwork)
        results = generate_mockups(
            artwork=dict(artwork),
            source_path=source_path,
            output_folder=workspace / "03 Mockups",
        )
        for result in results:
            upsert_artwork_file(
                artwork_code=artwork_code,
                role=result["role"],
                relative_path=str(result["path"].relative_to(workspace)),
                stored_filename=result["stored_filename"],
                original_filename=result["original_filename"],
            )
        set_artwork_production_flags(artwork_code, mockups_ready=False)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?mockups_generated=8#mockup-workspace",
        status_code=status.HTTP_303_SEE_OTHER,
    )

@app.post("/artworks/{artwork_code}/files/mockup")
def upload_mockup_file(
    artwork_code: str,
    slot_key: str = Form(...),
    upload: UploadFile = File(...),
):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    allowed_slots = set(GENERATED_SLOTS)
    if slot_key not in allowed_slots:
        raise HTTPException(status_code=400, detail="Invalid mockup slot")

    try:
        saved = save_uploaded_file(
            artwork=artwork,
            upload=upload,
            role="mockup",
            ratio=slot_key,
        )
        upsert_artwork_file(artwork_code=artwork_code, **saved)
        set_artwork_production_flags(artwork_code, mockups_ready=False)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        upload.file.close()

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?mockup_saved={slot_key}#mockup-workspace",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/mockups/{slot_key}/generate")
def generate_one_listing_image_post(artwork_code: str, slot_key: str):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    if slot_key not in GENERATED_SLOTS:
        raise HTTPException(status_code=400, detail="Invalid listing image slot")

    assignments = {
        row["role"]: row
        for row in get_artwork_file_assignments(artwork_code)
    }
    source_assignment = assignments.get("print_master") or assignments.get("source")
    if source_assignment is None:
        raise HTTPException(
            status_code=400,
            detail="Upload an artwork file before generating listing images",
        )

    try:
        source_path = resolve_assigned_file(artwork, source_assignment)
        workspace = get_artwork_folder(artwork)
        result = generate_listing_image(
            slot_key=slot_key,
            artwork=dict(artwork),
            source_path=source_path,
            output_folder=workspace / "03 Mockups",
        )
        upsert_artwork_file(
            artwork_code=artwork_code,
            role=result["role"],
            relative_path=str(result["path"].relative_to(workspace)),
            stored_filename=result["stored_filename"],
            original_filename=result["original_filename"],
        )
        set_artwork_production_flags(artwork_code, mockups_ready=False)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?listing_image_generated={slot_key}#mockup-workspace",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/mockups/settings")
async def save_mockup_settings(artwork_code: str, request: Request):
    form = await request.form()
    positions = {}
    try:
        for slot_key in GENERATED_SLOTS:
            positions[slot_key] = int(form[f"{slot_key}_position"])
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Every listing image needs an Etsy position") from error

    expected = list(range(1, len(GENERATED_SLOTS) + 1))
    if sorted(positions.values()) != expected:
        raise HTTPException(
            status_code=400,
            detail=f"Use each Etsy position from 1 through {len(GENERATED_SLOTS)} exactly once",
        )

    ordered_slots = [
        slot for slot, _ in sorted(positions.items(), key=lambda item: item[1])
    ]
    save_artwork_mockup_order(artwork_code, ordered_slots)

    context = _artwork_context(artwork_code)
    reviewed = form.get("reviewed") == "true"
    if reviewed and not context["production_summary"]["mockups_complete"]:
        raise HTTPException(
            status_code=400,
            detail="Generate or upload all eight listing images before marking them reviewed",
        )
    set_artwork_production_flags(artwork_code, mockups_ready=reviewed)

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?mockup_settings_saved=1#mockup-workspace",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/artworks/{artwork_code}/files/view")
def view_assigned_file(artwork_code: str, role: str = Query(...)):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    assignments = {
        row["role"]: row
        for row in get_artwork_file_assignments(artwork_code)
    }
    assignment = assignments.get(role)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assigned file not found")

    workspace = get_artwork_folder(artwork).resolve()
    file_path = (workspace / assignment["relative_path"]).resolve()
    try:
        file_path.relative_to(workspace)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid file path") from error

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path)


@app.post("/artworks/{artwork_code}/ratios/review")
def mark_ratio_review(
    artwork_code: str,
    reviewed: bool = Form(False),
):
    set_artwork_production_flags(
        artwork_code,
        ratio_exports_ready=reviewed,
    )
    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?ratio_review_saved=1#ratio-management",
        status_code=status.HTTP_303_SEE_OTHER,
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
