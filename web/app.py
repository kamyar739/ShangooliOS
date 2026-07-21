from pathlib import Path
import secrets
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
from PIL import Image, UnidentifiedImageError

from app.database import (
    create_artwork as create_artwork_with_workspace,
    get_artwork_folder,
)
from web.db import (
    archive_artwork,
    archive_collection,
    clear_inactive_etsy_link,
    create_collection,
    create_listing,
    create_mockup_scene,
    duplicate_listing,
    delete_listing,
    disable_mockup_scene,
    get_artwork,
    get_artwork_file_assignments,
    get_artwork_certification,
    get_print_master_certification,	
    get_artwork_mockup_order,
    get_artwork_mockup_templates,
    get_artwork_intelligence,
    get_artwork_listing_content,
    get_artwork_production,
    get_collection,
    get_dashboard,
    get_listing,
    get_listing_readiness,
    get_listing_status_counts,
    get_artwork_listings,
    get_mockup_scene,
    invalidate_artwork_after_source_change,
    restore_artwork,
    list_listings,
    list_mockup_scenes,
    link_etsy_listing,
    mark_etsy_synced,
    record_etsy_state,
    record_etsy_inventory_quantity,
    record_ai_enhancement,
    record_publishing_recovery,
    publish_listing,
    save_printify_product,
    mark_printify_etsy_connected,
    mark_printify_publish_requested,
    save_artwork_mockup_order,
    save_artwork_mockup_template,
    save_artwork_mockup_templates,
    save_collection_order,
    search_artworks,
    set_artwork_production_flags,
    update_artwork,
    update_artwork_status,
    update_artwork_intelligence,
    update_artwork_listing_content,
    update_artwork_production,
    update_collection,
    update_listing,
    update_mockup_scene_placement,
    upsert_artwork_file,
    upsert_artwork_certification,
    upsert_print_master_certification,
)
from web.etsy_api import (
    EtsyAPIError,
    begin_etsy_oauth,
    clear_etsy_config,
    complete_etsy_oauth,
    etsy_config,
    get_etsy_listing,
    update_etsy_listing,
    update_etsy_listing_state,
)
from web.etsy_sync import (
    build_etsy_sync_preview,
    find_etsy_candidates,
    set_etsy_inventory_quantity,
    sync_etsy_listing,
)
from web.file_intake import save_uploaded_file
from web.artwork_intelligence import analyze_artwork
from web.artwork_certifier import certify_artwork
from web.ai_upscaler import candidate_path, upscale_candidate
from web.listing_writer import generate_listing_content
from web.mockup_generator import (
    GENERATED_SLOTS,
    generate_listing_image,
    generate_mockups,
    generate_scene_mockup,
)
from web.marketplace_export import build_listing_export, inspect_listing_export
from web.printify import validate_printify_product
from web.printify_handoff import build_printify_handoff, inspect_printify_handoff
from web.printify_api import (
    PrintifyAPI,
    PrintifyAPIError,
    PrintifyPublishPending,
    clear_printify_local_config,
    clear_printify_runtime,
    complete_printify_runtime,
    configure_printify_runtime,
    configure_printify_token_runtime,
    create_printify_product,
    poster_blueprints,
    printify_configuration_source,
    ratio_role_for_variant,
    save_printify_local_config,
    variant_orientation,
    update_printify_product_artwork,
    wait_for_product_unlock,
)
from web.template_packs import DEFAULT_TEMPLATE_PACK, template_pack_options
from web.print_master import build_print_master, load_print_master_manifest
from web.production import (
    build_production_summary,
    list_workspace_files,
)
from web.ratio_profiles import get_ratio_profile
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
MOCKUP_SCENES_DIR = BASE_DIR.parent / "data" / "mockup_scenes"

app = FastAPI(title="ShangooliOS")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _price_to_cents(price: str) -> int:
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

    try:
        value = Decimal(price.strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, AttributeError):
        raise HTTPException(status_code=400, detail="Enter a valid price")
    if value < 0:
        raise HTTPException(status_code=400, detail="Price cannot be negative")
    return int(value * 100)


def _certified_orientation(artwork_code: str) -> str | None:
    master = get_print_master_certification(artwork_code)
    if master and master["valid"] and master["orientation"]:
        return master["orientation"]
    source = get_artwork_certification(artwork_code)
    if source and source["valid"] and source["orientation"]:
        return source["orientation"]
    return None


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


def _artwork_context(artwork_code: str, active_stage="details", **extra):
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
    saved_templates = {
        row["slot_key"]: row["template_key"]
        for row in get_artwork_mockup_templates(artwork_code)
    }
    for item in production_summary["mockup_status"]:
        item["position"] = saved_order.get(
            item["slot_key"], item["default_position"]
        )
        item["template_key"] = saved_templates.get(
            item["slot_key"], DEFAULT_TEMPLATE_PACK
        )
    production_summary["mockup_status"].sort(
        key=lambda item: item["position"]
    )

    artwork_listings = get_artwork_listings(artwork_code)
    auto_update_listing = next((
        item for item in artwork_listings
        if item["status"] == "published"
        and item["printify_product_id"] and item["external_listing_id"]
    ), None)
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
        "listings": artwork_listings,
        "certification": get_artwork_certification(artwork_code),
        "print_master_certification": get_print_master_certification(artwork_code),
        "certified_orientation": _certified_orientation(artwork_code),
        "template_packs": template_pack_options(),
        "mockup_scenes": list_mockup_scenes(
            orientation=production["orientation"] if production else None
        ),
        "default_template_pack": DEFAULT_TEMPLATE_PACK,
        "saved_template_packs": saved_templates,
        "print_master_manifest": load_print_master_manifest(artwork),
        "ai_upscale_candidate": candidate_path(artwork).is_file(),
        "auto_update_listing": auto_update_listing,
        "workflow_nav": _workflow_navigation(
            artwork,
            production=production,
            assignments=assignments,
            listings=artwork_listings,
            active_stage=active_stage,
        ),
    }
    context.update(extra)
    return context


def _workflow_navigation(
    artwork,
    *,
    production=None,
    assignments=None,
    listings=None,
    listing=None,
    active_stage="details",
):
    production = production or get_artwork_production(artwork["artwork_code"])
    assignments = assignments or get_artwork_file_assignments(artwork["artwork_code"])
    listings = list(listings or get_artwork_listings(artwork["artwork_code"]))
    listing = listing or (listings[0] if listings else None)
    roles = {row["role"] for row in assignments}
    _, collection_artworks, _ = get_collection(artwork["collection_code"])
    artwork_url = f"/artworks/{artwork['artwork_code']}"
    certification = get_artwork_certification(artwork["artwork_code"])
    has_source = "source" in roles
    has_print_files = "print_master" in roles or any(role.startswith("ratio:") for role in roles)
    has_mockups = any(role.startswith("mockup:") for role in roles)
    has_listing_work = bool(listing or get_artwork_listing_content(artwork["artwork_code"])["etsy_title"])
    print_complete = bool(production["print_master_ready"] and production["ratio_exports_ready"])
    all_current = bool(
        has_source and production["original_approved"] and print_complete
        and production["mockups_ready"] and production["listing_content_ready"]
    )
    live_listing = next(
        (item for item in listings if item["status"] == "published" and item["external_listing_id"]),
        None,
    )

    def stage(key, label, state, complete=False):
        labels = {
            "not_started": "Not started", "in_progress": "In progress",
            "needs_review": "Needs review", "out_of_date": "Out of date",
            "complete": "Complete", "published": "Published",
            "unpublished_changes": "Unpublished changes",
        }
        return {
            "key": key, "label": label, "href": f"{artwork_url}?step={key}",
            "state": state, "state_label": labels[state], "complete": complete,
        }

    stages = [
        stage("details", "Details", "complete" if artwork["public_title"] else "in_progress", bool(artwork["public_title"])),
        stage("source", "Source", "complete" if has_source else "not_started", has_source),
        stage(
            "certification", "Quality",
            "complete" if certification and production["original_approved"] else "needs_review" if certification else "not_started",
            bool(certification and production["original_approved"]),
        ),
        stage(
            "print", "Print files",
            "complete" if print_complete else "out_of_date" if has_print_files else "not_started",
            print_complete,
        ),
        stage(
            "mockups", "Mockups",
            "complete" if production["mockups_ready"] else "out_of_date" if has_mockups else "not_started",
            bool(production["mockups_ready"]),
        ),
        stage(
            "listing", "Listing",
            "complete" if production["listing_content_ready"] and listing else "out_of_date" if has_listing_work else "not_started",
            bool(production["listing_content_ready"] and listing),
        ),
        stage(
            "publish", "Publish",
            "published" if live_listing and all_current and live_listing["etsy_last_synced_at"]
            else "unpublished_changes" if live_listing
            else "in_progress" if listing and listing["printify_product_id"]
            else "not_started",
            bool(live_listing and all_current and live_listing["etsy_last_synced_at"]),
        ),
    ]
    normalized_active = {
        "printify": "publish", "etsy": "publish"
    }.get(active_stage, active_stage)
    return {
        "collection": {"code": artwork["collection_code"], "name": artwork["collection_name"]},
        "artwork": {"code": artwork["artwork_code"], "title": artwork["public_title"]},
        "collection_artworks": collection_artworks,
        "stages": stages,
        "active_stage": normalized_active,
    }


@app.get("/")
def home(request: Request, dashboard_view: str = Query("artworks", alias="view")):
    normalized_view = dashboard_view.strip().lower()
    if normalized_view not in ("", "artworks", "listings", "ready", "attention"):
        raise HTTPException(status_code=400, detail="Invalid dashboard view")
    context = get_dashboard()
    context["dashboard_view"] = normalized_view
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=context,
    )


def build_collection_sequence(collection, artworks):
    artworks_by_number = {
        int(item["artwork_code"].rsplit("-", 1)[-1]): item for item in artworks
    }
    upper_bound = max(
        collection["target_artwork_count"] or 0,
        max(artworks_by_number, default=0),
    )
    return [
        {"number": number, "artwork": artworks_by_number.get(number)}
        for number in range(1, upper_bound + 1)
    ]


@app.get("/collections")
def collections_page(
    request: Request,
    collection_code: str = Query("", alias="collection"),
    show_retired: bool = Query(False),
):
    context = get_dashboard()
    normalized_code = collection_code.strip().upper()
    if not normalized_code and context["collections"]:
        normalized_code = context["collections"][0]["code"]
    context["selected_collection"] = None
    context["collection_artworks"] = []
    if normalized_code:
        collection, artworks, retired_artworks = get_collection(normalized_code)
        if collection is None or collection["status"] == "archived":
            raise HTTPException(status_code=404, detail="Collection not found")
        context["selected_collection"] = collection
        context["collection_artworks"] = artworks
        context["retired_artworks"] = retired_artworks
        context["show_retired"] = show_retired
        context["collection_sequence"] = build_collection_sequence(
            collection, artworks
        )
    return templates.TemplateResponse(
        request=request,
        name="collections_index.html",
        context=context,
    )


@app.get("/mockup-studio")
def mockup_studio_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="mockup_studio.html",
        context={"scenes": list_mockup_scenes()},
    )


@app.post("/mockup-studio/scenes")
def create_mockup_scene_post(
    name: str = Form(...), room_type: str = Form(...),
    orientation: str = Form("any"), upload: UploadFile = File(...),
    placement_x: float = Form(25), placement_y: float = Form(15),
    placement_width: float = Form(50), placement_height: float = Form(50),
    source_url: str = Form(""), creator: str = Form(""),
    license_name: str = Form(""),
):
    normalized_orientation = orientation.strip().lower()
    if normalized_orientation not in {"horizontal", "vertical", "square", "any"}:
        raise HTTPException(status_code=400, detail="Choose a valid artwork orientation")
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=400, detail="Upload a JPG, PNG, or WebP room image")
    MOCKUP_SCENES_DIR.mkdir(parents=True, exist_ok=True)
    destination = MOCKUP_SCENES_DIR / f"scene-{secrets.token_hex(8)}{suffix}"
    try:
        with destination.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        with Image.open(destination) as image:
            image.verify()
        create_mockup_scene(
            name=name, room_type=room_type, orientation=normalized_orientation,
            image_path=destination.name, placement_x=placement_x,
            placement_y=placement_y, placement_width=placement_width,
            placement_height=placement_height,
            source_url=source_url, creator=creator, license_name=license_name,
        )
    except (ValueError, UnidentifiedImageError, OSError) as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        upload.file.close()
    return RedirectResponse(
        "/mockup-studio?scene_saved=1", status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/mockup-studio/scenes/{scene_id}/image")
def view_mockup_scene(scene_id: int):
    scene = get_mockup_scene(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="Mockup scene not found")
    path = MOCKUP_SCENES_DIR / scene["image_path"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Mockup scene image not found")
    return FileResponse(path)


@app.post("/mockup-studio/scenes/{scene_id}/placement")
def update_mockup_scene_placement_post(
    scene_id: int, placement_x: float = Form(...), placement_y: float = Form(...),
    placement_width: float = Form(...), placement_height: float = Form(...),
):
    try:
        update_mockup_scene_placement(
            scene_id, placement_x=placement_x, placement_y=placement_y,
            placement_width=placement_width, placement_height=placement_height,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        "/mockup-studio?scene_updated=1", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/mockup-studio/scenes/{scene_id}/disable")
def disable_mockup_scene_post(scene_id: int):
    try:
        disable_mockup_scene(scene_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return RedirectResponse(
        "/mockup-studio?scene_disabled=1", status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/recent")
def recently_updated_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="recently_updated.html",
        context=get_dashboard(),
    )


@app.post("/collections/order")
async def reorder_collections(request: Request):
    try:
        payload = await request.json()
        codes = payload.get("codes", [])
        if not isinstance(codes, list):
            raise ValueError("Collection order must be a list")
        save_collection_order(codes)
    except (ValueError, AttributeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"saved": True}


@app.get("/etsy/connect")
def etsy_connect_page(request: Request):
    config = etsy_config()
    return templates.TemplateResponse(
        request=request,
        name="etsy_connect.html",
        context={
            "config": config,
            "connected": bool(config["access_token"] and config["shop_id"]),
            "error": None,
        },
    )


@app.get("/printify/connect")
def printify_connect_page(request: Request):
    api = PrintifyAPI.from_env()
    return templates.TemplateResponse(
        request=request,
        name="printify_connect.html",
        context={
            "configured": api is not None,
            "source": printify_configuration_source(),
            "shop_id": api.shop_id if api else "",
        },
    )


@app.post("/printify/connect")
def printify_connect_save(api_token: str = Form(...), shop_id: str = Form(...)):
    try:
        save_printify_local_config(api_token, shop_id)
        configure_printify_runtime(api_token, shop_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse("/printify/connect?saved=1", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/printify/disconnect")
def printify_disconnect():
    clear_printify_runtime()
    clear_printify_local_config()
    return RedirectResponse("/printify/connect?disconnected=1", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/etsy/connect")
def etsy_connect_post(
    api_key: str = Form(...),
    shared_secret: str = Form(...),
    remember: bool = Form(False),
):
    try:
        authorization_url = begin_etsy_oauth(api_key, shared_secret, remember)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(authorization_url, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/etsy/oauth/callback")
def etsy_oauth_callback(
    request: Request,
    code: str = Query(""),
    state: str = Query(""),
    error: str = Query(""),
    error_description: str = Query(""),
):
    if error:
        message = error_description or error
    else:
        try:
            complete_etsy_oauth(code, state)
            return RedirectResponse(
                "/etsy/connect?connected=1", status_code=status.HTTP_303_SEE_OTHER
            )
        except (EtsyAPIError, KeyError, ValueError) as failure:
            message = str(failure)
    config = etsy_config()
    return templates.TemplateResponse(
        request=request,
        name="etsy_connect.html",
        context={"config": config, "connected": False, "error": message},
        status_code=400,
    )


@app.post("/etsy/disconnect")
def etsy_disconnect_post():
    clear_etsy_config()
    return RedirectResponse("/etsy/connect", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/etsy/reconnect")
def etsy_reconnect_post():
    config = etsy_config()
    if not config["api_key"] or not config["shared_secret"]:
        return RedirectResponse("/etsy/connect", status_code=status.HTTP_303_SEE_OTHER)
    authorization_url = begin_etsy_oauth(
        config["api_key"], config["shared_secret"], remember=True
    )
    return RedirectResponse(authorization_url, status_code=status.HTTP_303_SEE_OTHER)


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


@app.get("/listings")
def listings_page(
    request: Request,
    listing_status: str = Query("", alias="status"),
    listing_view: str = Query("", alias="view"),
):
    normalized_status = listing_status.strip().lower()
    normalized_view = listing_view.strip().lower()
    if normalized_view not in ("", "ready", "attention"):
        raise HTTPException(status_code=400, detail="Invalid listing view")
    if normalized_status and normalized_view:
        raise HTTPException(status_code=400, detail="Choose a status or readiness view, not both")
    try:
        listing_rows = list_listings(normalized_status or None)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    listings = []
    for row in listing_rows:
        item = dict(row)
        item["readiness"] = get_listing_readiness(item["id"])
        listings.append(item)
    if normalized_view == "ready":
        listings = [
            item for item in listings
            if item["readiness"]["ready"]
            and item["status"] not in ("published", "archived")
        ]
    elif normalized_view == "attention":
        listings = [
            item for item in listings
            if not item["readiness"]["ready"] and item["status"] != "archived"
        ]
    return templates.TemplateResponse(
        request=request,
        name="listings.html",
        context={
            "listings": listings,
            "active_status": normalized_status,
            "active_view": normalized_view,
            "statuses": ("draft", "ready", "published", "archived"),
            "status_counts": get_listing_status_counts(),
        },
    )


@app.get("/artworks/{artwork_code}/listings/new")
def new_listing_form(request: Request, artwork_code: str):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    content = get_artwork_listing_content(artwork_code)
    return templates.TemplateResponse(
        request=request,
        name="listing_form.html",
        context={
            "artwork": artwork,
            "listing": None,
            "prefill": content,
            "statuses": ("draft", "ready", "archived"),
            "workflow_nav": _workflow_navigation(artwork, active_stage="listing"),
        },
    )


@app.post("/artworks/{artwork_code}/listings/new")
def create_listing_post(
    artwork_code: str,
    marketplace: str = Form("Etsy"),
    product: str = Form("Poster"),
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
    price: str = Form("0.00"),
    listing_status: str = Form("draft"),
):
    if listing_status == "published":
        raise HTTPException(
            status_code=400,
            detail="Create the listing first, then use the Etsy publishing section",
        )
    try:
        listing_id = create_listing(
            artwork_code, marketplace=marketplace.strip() or "Etsy",
            product=product.strip() or "Poster", title=title.strip(),
            description=description.strip(), tags=tags.strip(),
            price_cents=_price_to_cents(price), status=listing_status,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/listings/{listing_id}")
def listing_page(request: Request, listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    readiness = get_listing_readiness(listing_id)
    printify_state = validate_printify_product(listing)
    production = get_artwork_production(listing["artwork_code"])
    available_printify_roles = {
        item["role"] for item in _printify_file_options(listing)
    }
    automatic_profile_roles = {
        ratio_role_for_variant(title)
        for _, title, _ in HORIZONTAL_PRINTIFY_PROFILE["variants"]
    }
    return templates.TemplateResponse(
        request=request,
        name="listing_form.html",
        context={
            "artwork": listing, "listing": listing, "prefill": None,
            "statuses": (
                ("draft", "ready", "published", "archived")
                if listing["status"] == "published"
                else ("draft", "ready", "archived")
            ),
            "readiness": readiness,
            "export_state": inspect_listing_export(listing, readiness),
            "printify_state": printify_state,
            "printify_automation_available": bool(
                readiness["ready"]
                and production
                and production["orientation"] == "horizontal"
                and automatic_profile_roles.issubset(available_printify_roles)
            ),
            "printify_handoff": (
                inspect_printify_handoff(listing, readiness)
                if printify_state["required"] else None
            ),
            "workflow_nav": _workflow_navigation(
                listing, listing=listing, active_stage="listing"
            ),
        },
    )


@app.post("/listings/{listing_id}/export")
def export_listing_post(listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    readiness = get_listing_readiness(listing_id)
    try:
        result = build_listing_export(listing, readiness)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return FileResponse(
        path=result["path"],
        filename=result["filename"],
        media_type="application/zip",
    )


@app.get("/listings/{listing_id}/etsy")
def etsy_sync_page(request: Request, listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        preview = build_etsy_sync_preview(listing)
        if preview.get("linked") and preview.get("remote"):
            record_etsy_state(listing_id, preview["remote"].get("state", ""))
            listing = get_listing(listing_id)
        error = None
    except EtsyAPIError as failure:
        preview = None
        error = str(failure)
    return templates.TemplateResponse(
        request=request,
        name="etsy_sync.html",
        context={
            "listing": listing,
            "preview": preview,
            "error": error,
            "workflow_nav": _workflow_navigation(
                listing, listing=listing, active_stage="etsy"
            ),
        },
    )


@app.post("/listings/{listing_id}/etsy/link")
def link_etsy_listing_post(listing_id: int, external_listing_id: str = Form(...)):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        remote = get_etsy_listing(external_listing_id.strip())
        config = etsy_config()
        if str(remote.get("shop_id", "")) != str(config["shop_id"]):
            raise ValueError("That listing does not belong to the connected Etsy shop")
        link_etsy_listing(listing_id, external_listing_id)
        record_etsy_state(listing_id, remote.get("state", ""))
    except (EtsyAPIError, ValueError) as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    return RedirectResponse(
        f"/listings/{listing_id}/etsy?linked=1", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/listings/{listing_id}/etsy/sync")
def sync_etsy_listing_post(listing_id: int, confirmed: bool = Form(False)):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the Etsy changes before syncing")
    readiness = get_listing_readiness(listing_id)
    if not readiness or not readiness["ready"]:
        raise HTTPException(status_code=400, detail="Complete listing readiness before syncing")
    try:
        result = sync_etsy_listing(listing)
        mark_etsy_synced(listing_id, result.get("state", ""))
    except (EtsyAPIError, ValueError) as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    return RedirectResponse(
        f"/listings/{listing_id}/etsy?synced=1", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/listings/{listing_id}/title/sync")
def sync_listing_title(listing_id: int, title: str = Form(...), confirmed: bool = Form(False)):
    listing = get_listing(listing_id)
    normalized = title.strip()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not normalized or len(normalized) > 140:
        raise HTTPException(status_code=400, detail="Enter a marketplace title up to 140 characters")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the marketplace title sync")
    try:
        if listing["printify_product_id"]:
            api = PrintifyAPI.from_env()
            if api is None:
                raise ValueError("Connect Printify before syncing the marketplace title")
            api.update_product(listing["printify_product_id"], {"title": normalized})
        if listing["external_listing_id"]:
            update_etsy_listing(
                listing["external_listing_id"], title=normalized,
                description=listing["description"] or "",
                tags=[tag.strip() for tag in (listing["tags"] or "").split(",") if tag.strip()],
            )
            mark_etsy_synced(listing_id, listing["etsy_state"] or "")
    except (PrintifyAPIError, EtsyAPIError, ValueError) as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    update_listing(
        listing_id, marketplace=listing["marketplace"], product=listing["product"],
        title=normalized, description=listing["description"] or "", tags=listing["tags"] or "",
        price_cents=listing["price_cents"], status=listing["status"],
    )
    return RedirectResponse(
        f"/artworks/{listing['artwork_code']}?step=details&marketplace_title_synced=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/etsy/inventory")
def update_etsy_inventory_post(
    listing_id: int,
    quantity: int = Form(...),
    confirmed: bool = Form(False),
):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the inventory change")
    try:
        set_etsy_inventory_quantity(listing, quantity)
        record_etsy_inventory_quantity(listing_id, quantity)
    except (EtsyAPIError, ValueError) as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    return RedirectResponse(
        f"/listings/{listing_id}/etsy?inventory_updated={quantity}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/etsy/inventory/sold-out")
def mark_etsy_listing_sold_out(listing_id: int, confirmed: bool = Form(False)):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the sold-out change")
    try:
        set_etsy_inventory_quantity(listing, 0)
        record_etsy_inventory_quantity(listing_id, 0)
    except (EtsyAPIError, ValueError) as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    return RedirectResponse("/listings?inventory_updated=0", status_code=303)


@app.post("/listings/{listing_id}/etsy/inventory/restore")
def restore_etsy_listing_inventory(listing_id: int, confirmed: bool = Form(False)):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the inventory restore")
    quantity = listing["etsy_inventory_restore_quantity"] or 2
    try:
        update_etsy_listing_state(str(listing["external_listing_id"]), "active")
        set_etsy_inventory_quantity(listing, quantity)
        record_etsy_inventory_quantity(listing_id, quantity)
    except (EtsyAPIError, ValueError) as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    return RedirectResponse(
        f"/listings?inventory_updated={quantity}", status_code=303
    )


@app.post("/listings/{listing_id}")
def update_listing_post(
    listing_id: int,
    marketplace: str = Form("Etsy"),
    product: str = Form("Poster"),
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
    price: str = Form("0.00"),
    listing_status: str = Form("draft"),
):
    current_listing = get_listing(listing_id)
    if current_listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing_status == "published" and current_listing["status"] != "published":
        raise HTTPException(
            status_code=400,
            detail="Use the Etsy publishing section to mark this listing published",
        )
    try:
        update_listing(
            listing_id, marketplace=marketplace.strip() or "Etsy",
            product=product.strip() or "Poster", title=title.strip(),
            description=description.strip(), tags=tags.strip(),
            price_cents=_price_to_cents(price), status=listing_status,
        )
    except ValueError as error:
        code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=code, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}?saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/publish")
def publish_listing_post(
    listing_id: int,
    marketplace_url: str = Form(...),
    external_listing_id: str = Form(...),
):
    try:
        publish_listing(
            listing_id,
            marketplace_url=marketplace_url,
            external_listing_id=external_listing_id,
        )
    except ValueError as error:
        code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=code, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}?published=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify")
def save_printify_product_post(
    listing_id: int,
    product_url: str = Form(...),
    product_id: str = Form(...),
    provider: str = Form(...),
    sizes: str = Form(...),
    base_cost: str = Form(...),
):
    try:
        save_printify_product(
            listing_id,
            product_url=product_url,
            product_id=product_id,
            provider=provider,
            sizes=sizes,
            base_cost_cents=_price_to_cents(base_cost),
        )
    except ValueError as error:
        code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=code, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}?printify_saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _printify_file_options(listing):
    workspace = get_artwork_folder(listing)
    options = []
    for assignment in get_artwork_file_assignments(listing["artwork_code"]):
        role = assignment["role"]
        if role == "print_master" or role.startswith("ratio:"):
            path = workspace / assignment["relative_path"]
            if path.is_file():
                options.append(
                    {
                        "role": role,
                        "label": role.replace("ratio:", "Ratio ").replace("print_master", "Print-ready file"),
                        "path": path,
                    }
                )
    return options


@app.get("/listings/{listing_id}/printify/create")
def create_printify_page(
    request: Request,
    listing_id: int,
    blueprint_id: int | None = None,
    provider_id: int | None = None,
):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    api = PrintifyAPI.from_env()
    token_api = api or PrintifyAPI.with_available_token()
    context = {
        "listing": listing,
        "workflow_nav": _workflow_navigation(
            listing, listing=listing, active_stage="printify"
        ),
        "configured": api is not None,
        "configuration_source": printify_configuration_source(),
        "token_available": token_api is not None,
        "shops": [],
        "blueprints": [], "providers": [], "variants": [],
        "blueprint_id": blueprint_id, "provider_id": provider_id,
        "provider_name": "", "print_files": _printify_file_options(listing),
        "error": None,
    }
    if api is None and token_api is not None:
        try:
            context["shops"] = token_api.list_shops()
        except PrintifyAPIError as error:
            context["error"] = str(error)
    if api is not None:
        try:
            production = get_artwork_production(listing["artwork_code"])
            artwork_orientation = production["orientation"] if production else None
            context["blueprints"] = poster_blueprints(
                api.list_blueprints(), artwork_orientation
            )
            if blueprint_id:
                context["providers"] = api.list_providers(blueprint_id)
            if blueprint_id and provider_id:
                provider = next(
                    (item for item in context["providers"] if item["id"] == provider_id),
                    None,
                )
                if provider is None:
                    raise ValueError("Choose a valid Printify provider")
                context["provider_name"] = provider["title"]
                context["variants"] = []
                available_file_roles = {
                    item["role"] for item in context["print_files"]
                }
                for item in api.list_variants(blueprint_id, provider_id):
                    if not item.get("is_available", True):
                        continue
                    variant = dict(item)
                    expected_role = ratio_role_for_variant(variant.get("title", ""))
                    variant["recommended_file_role"] = (
                        expected_role if expected_role in available_file_roles else None
                    )
                    context["variants"].append(variant)
        except (PrintifyAPIError, ValueError) as error:
            context["error"] = str(error)
    return templates.TemplateResponse(
        request=request, name="printify_create.html", context=context
    )


HORIZONTAL_PRINTIFY_PROFILE = {
    "blueprint_id": 284,
    "provider_id": 99,
    "provider_name": "Printify Choice",
    "variants": (
        (43163, '14″ x 11″ / Matte', 2500),
        (43166, '18″ x 12″ / Matte', 2800),
        (43169, '20″ x 16″ / Matte', 3200),
        (43172, '24″ x 18″ / Matte', 3800),
        (43175, '30″ x 20″ / Matte', 4800),
        (43178, '36″ x 24″ / Matte', 5800),
    ),
}


@app.post("/listings/{listing_id}/printify/prepare")
def prepare_printify_product_post(
    listing_id: int,
    confirmed: bool = Form(False),
):
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the Printify draft setup")
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing["printify_product_id"]:
        raise HTTPException(status_code=400, detail="This listing already has a Printify product")
    readiness = get_listing_readiness(listing_id)
    if not readiness or not readiness["ready"]:
        raise HTTPException(status_code=400, detail="Complete listing readiness first")
    production = get_artwork_production(listing["artwork_code"])
    if not production or production["orientation"] != "horizontal":
        raise HTTPException(
            status_code=400,
            detail="The automatic Printify profile currently supports horizontal artwork only",
        )
    api = PrintifyAPI.from_env()
    if api is None:
        raise HTTPException(status_code=400, detail="Printify API is not configured")

    profile = HORIZONTAL_PRINTIFY_PROFILE
    file_options = {item["role"]: item for item in _printify_file_options(listing)}
    try:
        providers = api.list_providers(profile["blueprint_id"])
        provider = next(
            item for item in providers
            if item["id"] == profile["provider_id"]
            and item["title"] == profile["provider_name"]
        )
        variants = {
            item["id"]: item
            for item in api.list_variants(profile["blueprint_id"], provider["id"])
        }
        selections = []
        for variant_id, expected_title, price_cents in profile["variants"]:
            variant = variants.get(variant_id)
            if not variant or variant.get("is_available") is False:
                raise ValueError(f"Printify size is unavailable: {expected_title}")
            if variant.get("title") != expected_title:
                raise ValueError(f"Printify changed the catalog size: {expected_title}")
            role = ratio_role_for_variant(expected_title)
            if role not in file_options:
                raise ValueError(f"Missing prepared file for {expected_title}: {role}")
            selections.append({
                "variant_id": variant_id,
                "title": expected_title,
                "cost_cents": None,
                "price_cents": price_cents,
                "path": file_options[role]["path"],
            })
        result = create_printify_product(
            api,
            listing=listing,
            blueprint_id=profile["blueprint_id"],
            provider_id=provider["id"],
            provider_name=provider["title"],
            selections=selections,
        )
        product = result["product"]
        clear_inactive_etsy_link(listing_id)
        save_printify_product(
            listing_id,
            product_url=result["product_url"],
            product_id=str(product["id"]),
            provider=result["provider"],
            sizes=result["sizes"],
            base_cost_cents=result["base_cost_cents"],
        )
    except (StopIteration, ValueError, PrintifyAPIError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}?printify_created=1&automatic=1#one-click-printify",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify/configure")
def configure_printify_post(
    listing_id: int,
    api_token: str = Form(...),
    shop_id: str = Form(...),
    remember: bool = Form(False),
):
    if get_listing(listing_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        configure_printify_runtime(api_token, shop_id)
        if remember:
            save_printify_local_config(api_token, shop_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}/printify/create?configured=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify/connect-token")
def connect_printify_token_post(
    listing_id: int,
    api_token: str = Form(...),
    remember: bool = Form(False),
):
    if get_listing(listing_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        configure_printify_token_runtime(api_token, remember=remember)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}/printify/create?token_saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify/select-shop")
def select_printify_shop_post(listing_id: int, shop_id: str = Form(...)):
    if get_listing(listing_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    api = PrintifyAPI.with_available_token()
    if api is None:
        raise HTTPException(status_code=400, detail="Enter the Printify API token first")
    try:
        shops = api.list_shops()
        selected = next(
            (shop for shop in shops if str(shop["id"]) == str(shop_id)), None
        )
        if selected is None:
            raise ValueError("Choose a valid Printify shop")
        complete_printify_runtime(str(selected["id"]))
    except (PrintifyAPIError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}/printify/create?configured=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify/replace-token")
def replace_printify_token_post(listing_id: int):
    if get_listing(listing_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    clear_printify_runtime()
    clear_printify_local_config()
    return RedirectResponse(
        url=f"/listings/{listing_id}/printify/create?replace_token=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify/create")
async def create_printify_product_post(request: Request, listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    api = PrintifyAPI.from_env()
    if api is None:
        raise HTTPException(status_code=400, detail="Printify API is not configured")
    form = await request.form()
    try:
        blueprint_id = int(form["blueprint_id"])
        provider_id = int(form["provider_id"])
        selected_ids = {int(value) for value in form.getlist("variant_ids")}
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Choose a product, provider, and variants") from error

    file_options = {item["role"]: item for item in _printify_file_options(listing)}
    try:
        production = get_artwork_production(listing["artwork_code"])
        artwork_orientation = production["orientation"] if production else None
        providers = api.list_providers(blueprint_id)
        provider = next(item for item in providers if item["id"] == provider_id)
        variants = {
            item["id"]: item for item in api.list_variants(blueprint_id, provider_id)
        }
        selections = []
        for variant_id in selected_ids:
            variant = variants[variant_id]
            selected_orientation = variant_orientation(variant["title"])
            if artwork_orientation in {"horizontal", "vertical", "square"} and (
                selected_orientation != artwork_orientation
            ):
                raise ValueError(
                    f"Choose {artwork_orientation} Printify sizes for this artwork; "
                    f"{variant['title']} is {selected_orientation or 'an unknown orientation'}."
                )
            role = form[f"file_{variant_id}"]
            expected_role = ratio_role_for_variant(variant["title"])
            if expected_role not in file_options:
                raise ValueError(
                    f"No prepared {expected_role or 'ratio'} print file is available for "
                    f"{variant['title']}."
                )
            if role != expected_role:
                raise ValueError(
                    f"Use the {expected_role.replace('ratio:', 'Ratio ')} print file for "
                    f"{variant['title']}."
                )
            file_option = file_options[role]
            selections.append(
                {
                    "variant_id": variant_id,
                    "title": variant["title"],
                    "cost_cents": (
                        int(variant["cost"]) if variant.get("cost") is not None else None
                    ),
                    "price_cents": _price_to_cents(form[f"price_{variant_id}"]),
                    "path": file_option["path"],
                }
            )
        result = create_printify_product(
            api,
            listing=listing,
            blueprint_id=blueprint_id,
            provider_id=provider_id,
            provider_name=provider["title"],
            selections=selections,
        )
        product = result["product"]
        save_printify_product(
            listing_id,
            product_url=result["product_url"],
            product_id=str(product["id"]),
            provider=result["provider"],
            sizes=result["sizes"],
            base_cost_cents=result["base_cost_cents"],
        )
    except (KeyError, StopIteration, ValueError, PrintifyAPIError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}?printify_created=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify/publish")
def publish_printify_product_post(listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    readiness = get_listing_readiness(listing_id)
    if not readiness["ready"]:
        raise HTTPException(
            status_code=400,
            detail="Complete the listing readiness checklist before publishing",
        )
    printify = validate_printify_product(listing)
    if not printify["ready"]:
        raise HTTPException(
            status_code=400,
            detail="Create or save the Printify product before publishing",
        )
    api = PrintifyAPI.from_env()
    if api is None:
        raise HTTPException(status_code=400, detail="Printify API is not configured")
    try:
        api.publish_product(listing["printify_product_id"])
        mark_printify_publish_requested(listing_id)
    except (PrintifyAPIError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}?printify_published=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/publishing/recover")
def recover_listing_publication_post(listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    printify = validate_printify_product(listing)
    if not printify["ready"]:
        raise HTTPException(status_code=400, detail="Create the Printify draft first")
    api = PrintifyAPI.from_env()
    if api is None:
        raise HTTPException(status_code=400, detail="Printify API is not configured")

    try:
        product = api.get_product(listing["printify_product_id"])
        product_title = (product.get("title") or listing["title"] or "").strip().casefold()
        external_id = str(listing["external_listing_id"] or "").strip()

        if not external_id:
            candidates = find_etsy_candidates(listing)
            exact = [
                item for item in candidates
                if (item.get("title") or "").strip().casefold() in {
                    product_title, (listing["title"] or "").strip().casefold()
                }
            ]
            if len(exact) == 1:
                external_id = str(exact[0]["listing_id"])
                link_etsy_listing(listing_id, external_id)
                record_etsy_state(listing_id, exact[0].get("state", ""))
                listing = get_listing(listing_id)
            elif len(exact) > 1:
                message = "More than one Etsy listing matches. Choose the correct listing on the Etsy publishing page."
                record_publishing_recovery(listing_id, "needs_review", message)
                return RedirectResponse(
                    f"/listings/{listing_id}?recovery_checked=1",
                    status_code=status.HTTP_303_SEE_OTHER,
                )
            else:
                if listing["printify_publish_requested_at"]:
                    message = "Printify is confirmed; Etsy has not returned a matching listing yet. Wait briefly, then check again."
                    stage = "waiting_for_etsy"
                else:
                    message = "The Printify draft is confirmed. It has not been sent to Etsy, so no publish action was repeated."
                    stage = "printify_draft_confirmed"
                record_publishing_recovery(listing_id, stage, message)
                return RedirectResponse(
                    f"/listings/{listing_id}?recovery_checked=1",
                    status_code=status.HTTP_303_SEE_OTHER,
                )

        listing = get_listing(listing_id)
        remote = get_etsy_listing(external_id)
        if str(remote.get("shop_id", "")) != str(etsy_config()["shop_id"]):
            raise ValueError("The linked Etsy listing belongs to a different shop")
        record_etsy_state(listing_id, remote.get("state", ""))
        preview = build_etsy_sync_preview(get_listing(listing_id))
        if preview.get("changed_count"):
            result = sync_etsy_listing(get_listing(listing_id))
            mark_etsy_synced(listing_id, result.get("state", ""))
            message = "Recovered the Etsy link and synchronized the ShangooliOS title, description, tags, images, and section. Final Etsy review remains."
        else:
            mark_etsy_synced(listing_id, remote.get("state", ""))
            message = "Printify and Etsy are linked and already synchronized. Final Etsy review remains."
        record_publishing_recovery(listing_id, "etsy_ready_for_review", message)
    except (EtsyAPIError, PrintifyAPIError, KeyError, ValueError) as failure:
        failure_text = str(failure)
        normalized_failure = failure_text.casefold()
        if "http 409" in normalized_failure and "being edited by another process" in normalized_failure:
            record_publishing_recovery(
                listing_id, "waiting_for_etsy",
                "The Etsy listing was found and linked, but Printify is still finishing its setup. Nothing needs to be repeated. Wait briefly, then check status again.",
            )
        else:
            record_publishing_recovery(
                listing_id, "recovery_failed",
                f"Recovery stopped safely: {failure_text}",
            )
    return RedirectResponse(
        f"/listings/{listing_id}?recovery_checked=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/printify-export")
def export_printify_handoff_post(listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        result = build_printify_handoff(listing, get_listing_readiness(listing_id))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return FileResponse(
        path=result["path"], filename=result["filename"], media_type="application/zip"
    )


@app.post("/listings/{listing_id}/printify-connected")
def mark_printify_connected_post(listing_id: int):
    try:
        mark_printify_etsy_connected(listing_id)
    except ValueError as error:
        code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=code, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{listing_id}?printify_connected=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/duplicate")
def duplicate_listing_post(listing_id: int):
    try:
        new_listing_id = duplicate_listing(listing_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return RedirectResponse(
        url=f"/listings/{new_listing_id}?duplicated=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/listings/{listing_id}/delete")
def delete_listing_post(listing_id: int):
    listing = get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        delete_listing(listing_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return RedirectResponse(
        url=f"/artworks/{listing['artwork_code']}",
        status_code=status.HTTP_303_SEE_OTHER,
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
    etsy_section_name: str = Form(""),
):
    collection_code = create_collection(
        code=code,
        name=name,
        target_artwork_count=target_artwork_count,
        status=collection_status,
        etsy_section_name=etsy_section_name,
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
            "collection_sequence": build_collection_sequence(collection, artworks),
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
    etsy_section_name: str = Form(""),
):
    update_collection(
        collection_code=collection_code,
        name=name,
        target_artwork_count=target_artwork_count,
        status=collection_status,
        etsy_section_name=etsy_section_name,
    )

    return RedirectResponse(
        url=f"/collections?collection={collection_code.upper()}",
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
    return RedirectResponse(url=f"/artworks/{artwork_code}?step=details", status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(url=f"/artworks/{artwork_code}?step=details", status_code=status.HTTP_303_SEE_OTHER)


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
        url=f"/artworks/{artwork_code}?step=listing",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/prepare")
def prepare_artwork_post(
    artwork_code: str,
    price: str = Form(...),
    confirmed: bool = Form(False),
):
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm automatic preparation")
    price_cents = _price_to_cents(price)
    if price_cents <= 0:
        raise HTTPException(status_code=400, detail="Enter a price greater than $0.00")

    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    production = get_artwork_production(artwork_code)
    assignments = {row["role"]: row for row in get_artwork_file_assignments(artwork_code)}
    source_assignment = assignments.get("source")
    if source_assignment is None:
        raise HTTPException(status_code=400, detail="Upload source artwork first")
    if not production["original_approved"]:
        raise HTTPException(status_code=400, detail="Approve the source artwork first")

    try:
        source_path = resolve_assigned_file(artwork, source_assignment)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    certified_orientation = _certified_orientation(artwork_code)
    if not certified_orientation:
        certification = certify_artwork(source_path).to_dict()
        if not certification["valid"]:
            raise HTTPException(
                status_code=400,
                detail="The source artwork did not pass automatic certification",
            )
        upsert_artwork_certification(artwork_code, certification)
        certified_orientation = certification["orientation"]
        ratio_profile = get_ratio_profile(certified_orientation)
        update_artwork_production(
            artwork_code=artwork_code,
            orientation=certified_orientation,
            master_ratio=ratio_profile["master_ratio"],
            required_ratios=", ".join(ratio_profile["required_ratios"]),
            original_approved=bool(production["original_approved"]),
            print_master_ready=bool(production["print_master_ready"]),
            ratio_exports_ready=bool(production["ratio_exports_ready"]),
            mockups_ready=bool(production["mockups_ready"]),
            listing_content_ready=bool(production["listing_content_ready"]),
            notes=production["notes"] or "",
        )
        production = get_artwork_production(artwork_code)
    if production["orientation"] != certified_orientation:
        raise HTTPException(
            status_code=400,
            detail=f"Orientation must match the certified {certified_orientation} artwork",
        )

    try:
        workspace = get_artwork_folder(artwork)
        if assignments.get("print_master") is None:
            master = build_print_master(artwork, source_path)
            upsert_artwork_file(
                artwork_code=artwork_code,
                role="print_master",
                relative_path=master.relative_path,
                stored_filename=master.master_filename,
                original_filename=source_assignment["original_filename"],
            )
            master_path = workspace / master.relative_path
            upsert_print_master_certification(
                artwork_code, certify_artwork(master_path).to_dict()
            )
            set_artwork_production_flags(artwork_code, print_master_ready=True)

        artwork = get_artwork(artwork_code)
        _generate_required_ratios(artwork, overwrite=False)
        assignments = {row["role"]: row for row in get_artwork_file_assignments(artwork_code)}
        required_ratios = {
            value.strip()
            for value in (production["required_ratios"] or "").split(",")
            if value.strip()
        }
        if not required_ratios or not all(f"ratio:{ratio}" in assignments for ratio in required_ratios):
            raise ValueError("Not all required ratio files could be generated")

        missing_mockups = [
            slot_key for slot_key in GENERATED_SLOTS
            if f"mockup:{slot_key}" not in assignments
        ]
        if missing_mockups:
            master_assignment = assignments.get("print_master") or source_assignment
            master_path = resolve_assigned_file(artwork, master_assignment)
            results = generate_mockups(
                artwork=dict(artwork),
                source_path=master_path,
                output_folder=workspace / "03 Mockups",
                template_key=DEFAULT_TEMPLATE_PACK,
            )
            for result in results:
                upsert_artwork_file(
                    artwork_code=artwork_code,
                    role=result["role"],
                    relative_path=str(result["path"].relative_to(workspace)),
                    stored_filename=result["stored_filename"],
                    original_filename=result["original_filename"],
                )
            save_artwork_mockup_templates(
                artwork_code,
                {slot_key: DEFAULT_TEMPLATE_PACK for slot_key in GENERATED_SLOTS},
            )

        source_path = resolve_assigned_file(artwork, source_assignment)
        intelligence = analyze_artwork(artwork, source_path)
        update_artwork_intelligence(artwork_code, **intelligence)
        listing_content = generate_listing_content(
            artwork, get_artwork_intelligence(artwork_code)
        )
        update_artwork_listing_content(artwork_code, **listing_content)
        if not (artwork["story"] or "").strip():
            update_artwork(
                artwork_code,
                artwork["public_title"],
                artwork["working_title"] or "",
                artwork["theme"] or "",
                listing_content["long_story"],
                artwork["status"],
            )

        set_artwork_production_flags(
            artwork_code,
            print_master_ready=True,
            ratio_exports_ready=True,
            mockups_ready=True,
            listing_content_ready=True,
        )

        listings = list(get_artwork_listings(artwork_code))
        editable_listing = next(
            (item for item in listings if item["status"] in ("draft", "ready")),
            None,
        )
        if editable_listing:
            prepared_listing_id = editable_listing["id"]
            update_listing(
                editable_listing["id"],
                marketplace=editable_listing["marketplace"],
                product=editable_listing["product"],
                title=editable_listing["title"] or listing_content["etsy_title"],
                description=editable_listing["description"] or listing_content["etsy_description"],
                tags=editable_listing["tags"] or listing_content["etsy_tags"],
                price_cents=price_cents,
                status="ready",
            )
        elif not listings:
            prepared_listing_id = create_listing(
                artwork_code,
                marketplace="Etsy",
                product="Poster",
                title=listing_content["etsy_title"],
                description=listing_content["etsy_description"],
                tags=listing_content["etsy_tags"],
                price_cents=price_cents,
                status="ready",
            )
        else:
            prepared_listing_id = listings[0]["id"]
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return RedirectResponse(
        url=f"/listings/{prepared_listing_id}?prepared=1",
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
        url=f"/artworks/{artwork_code}?step=listing",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/artworks/{artwork_code}")
def artwork_page(
    request: Request, artwork_code: str,
    step: str = Query("details"),
):
    allowed_steps = {
        "details", "source", "certification", "print", "mockups", "listing", "publish"
    }
    active_step = step if step in allowed_steps else "details"
    return templates.TemplateResponse(
        request=request,
        name="artwork.html",
        context=_artwork_context(
            artwork_code,
            active_stage=active_step,
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
        url=f"/artworks/{artwork_code.upper()}?step=details",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/status")
def save_artwork_status(
    artwork_code: str,
    artwork_status: str = Form(..., alias="status"),
    return_to: str = Form("/collections"),
):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    try:
        update_artwork_status(artwork_code, artwork_status)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    safe_return = return_to if return_to.startswith("/") and not return_to.startswith("//") else "/collections"
    return RedirectResponse(url=safe_return, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/artworks/{artwork_code}/production")
def save_artwork_production(
    artwork_code: str,
    orientation: str = Form(""),
    original_approved: bool = Form(False),
    print_master_ready: bool = Form(False),
    ratio_exports_ready: bool = Form(False),
    mockups_ready: bool = Form(False),
    listing_content_ready: bool = Form(False),
    production_notes: str = Form(""),
):
    certified_orientation = _certified_orientation(artwork_code)
    if certified_orientation and orientation != certified_orientation:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Orientation is locked to {certified_orientation} by the certified "
                "print-ready file. Replace or rotate that file to change it."
            ),
        )
    effective_orientation = certified_orientation or orientation
    ratio_profile = get_ratio_profile(effective_orientation)

    update_artwork_production(
        artwork_code=artwork_code,
        orientation=effective_orientation,
        master_ratio=ratio_profile["master_ratio"],
        required_ratios=", ".join(ratio_profile["required_ratios"]),
        original_approved=original_approved,
        print_master_ready=print_master_ready,
        ratio_exports_ready=ratio_exports_ready,
        mockups_ready=mockups_ready,
        listing_content_ready=listing_content_ready,
        notes=production_notes,
    )

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=print&production_saved=1",
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
        invalidate_artwork_after_source_change(artwork_code)
        upsert_artwork_file(
            artwork_code=artwork_code,
            **saved,
        )
        workspace = get_artwork_folder(artwork)
        source_path = workspace / saved["relative_path"]
        certification = certify_artwork(source_path).to_dict()
        upsert_artwork_certification(artwork_code, certification)

        if use_as_master:
            master = build_print_master(artwork, source_path)
            upsert_artwork_file(
                artwork_code=artwork_code,
                role="print_master",
                relative_path=master.relative_path,
                stored_filename=master.master_filename,
                original_filename=saved["original_filename"],
            )
            set_artwork_production_flags(
                artwork_code,
                print_master_ready=True,
            )
            master_path = workspace / master.relative_path
            upsert_print_master_certification(
                artwork_code,
                certify_artwork(master_path).to_dict(),
            )
            _generate_required_ratios(artwork, overwrite=True)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        upload.file.close()

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=source&file_saved=source",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/ai-upscale")
def generate_ai_upscale(artwork_code: str):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    production = get_artwork_production(artwork_code)
    if production["ai_enhanced_at"]:
        raise HTTPException(
            status_code=400,
            detail="This source has already been AI enhanced. Upload a new original to reset it.",
        )
    assignments = {row["role"]: row for row in get_artwork_file_assignments(artwork_code)}
    if "source" not in assignments:
        raise HTTPException(status_code=400, detail="Upload source artwork first")
    try:
        source = resolve_assigned_file(artwork, assignments["source"])
        upscale_candidate(artwork, source)
    except ValueError as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    return RedirectResponse(
        f"/artworks/{artwork_code.upper()}?step=certification&ai_upscaled=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/artworks/{artwork_code}/ai-upscale/view")
def view_ai_upscale(artwork_code: str):
    artwork = get_artwork(artwork_code)
    if artwork is None or not candidate_path(artwork).is_file():
        raise HTTPException(status_code=404, detail="AI upscale not found")
    return FileResponse(candidate_path(artwork), media_type="image/png")


@app.post("/artworks/{artwork_code}/certification/approve")
def approve_current_source_certification(
    artwork_code: str, confirmed: bool = Form(False),
):
    artwork = get_artwork(artwork_code)
    certification = get_artwork_certification(artwork_code)
    if artwork is None or certification is None:
        raise HTTPException(status_code=400, detail="Certify a source artwork first")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the source review")
    set_artwork_production_flags(artwork_code, original_approved=True)
    return RedirectResponse(
        f"/artworks/{artwork_code.upper()}?step=certification&certification_approved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/ai-upscale/approve")
def approve_ai_upscale(artwork_code: str, confirmed: bool = Form(False)):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    path = candidate_path(artwork)
    if not confirmed or not path.is_file():
        raise HTTPException(status_code=400, detail="Review and approve the AI upscale first")
    production = get_artwork_production(artwork_code)
    if production["ai_enhanced_at"]:
        raise HTTPException(
            status_code=400,
            detail="This source has already been AI enhanced. Upload a new original to reset it.",
        )
    current_certification = get_artwork_certification(artwork_code)
    workspace = get_artwork_folder(artwork)
    approved_path = path.with_name(f"{artwork_code.upper()}_ai_upscaled_approved.png")
    shutil.copy2(path, approved_path)
    certification = certify_artwork(approved_path).to_dict()
    invalidate_artwork_after_source_change(artwork_code)
    upsert_artwork_file(
        artwork_code=artwork_code, role="source",
        relative_path=str(approved_path.relative_to(workspace)), stored_filename=approved_path.name,
        original_filename=approved_path.name,
    )
    upsert_artwork_certification(artwork_code, certification)
    master = build_print_master(artwork, approved_path)
    upsert_artwork_file(
        artwork_code=artwork_code, role="print_master", relative_path=master.relative_path,
        stored_filename=master.master_filename, original_filename=path.name,
    )
    upsert_print_master_certification(
        artwork_code, certify_artwork(workspace / master.relative_path).to_dict()
    )
    _generate_required_ratios(artwork, overwrite=True)
    set_artwork_production_flags(
        artwork_code, original_approved=True, print_master_ready=True,
        ratio_exports_ready=False, mockups_ready=False,
    )
    record_ai_enhancement(
        artwork_code,
        original_width=current_certification["width"] if current_certification else 0,
        original_height=current_certification["height"] if current_certification else 0,
        enhanced_width=certification["width"], enhanced_height=certification["height"],
    )
    path.unlink()
    live_listing = next((
        item for item in get_artwork_listings(artwork_code)
        if item["status"] == "published"
        and item["printify_product_id"] and item["external_listing_id"]
    ), None)
    update_pending = False
    if live_listing:
        update_result = update_artwork_everywhere(
            artwork_code, live_listing["id"], upload=None, confirmed=True
        )
        update_pending = "update_pending=1" in update_result.headers.get("location", "")
    return RedirectResponse(
        f"/artworks/{artwork_code.upper()}?step=certification&ai_upscale_approved=1"
        f"{'&update_pending=1' if update_pending else '&updated_everywhere=1' if live_listing else ''}"
        "",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/listings/{listing_id}/update-everywhere")
def update_artwork_everywhere(
    artwork_code: str,
    listing_id: int,
    upload: UploadFile | None = File(None),
    confirmed: bool = Form(False),
):
    artwork = get_artwork(artwork_code)
    listing = get_listing(listing_id)
    if artwork is None or listing is None or listing["artwork_code"] != artwork_code.upper():
        raise HTTPException(status_code=404, detail="Artwork listing not found")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Approve the replacement artwork first")
    if not listing["printify_product_id"] or not listing["external_listing_id"]:
        raise HTTPException(status_code=400, detail="Connect both Printify and Etsy before updating everywhere")
    api = PrintifyAPI.from_env()
    if api is None:
        raise HTTPException(status_code=400, detail="Connect Printify before updating everywhere")
    try:
        workspace = get_artwork_folder(artwork)
        if upload and upload.filename:
            saved = save_uploaded_file(artwork=artwork, upload=upload, role="source")
            invalidate_artwork_after_source_change(artwork_code)
            upsert_artwork_file(artwork_code=artwork_code, **saved)
            source_path = workspace / saved["relative_path"]
            original_filename = saved["original_filename"]
        else:
            assignments = {row["role"]: row for row in get_artwork_file_assignments(artwork_code)}
            if "source" not in assignments:
                raise ValueError("Upload or approve replacement artwork first")
            source_path = resolve_assigned_file(artwork, assignments["source"])
            original_filename = assignments["source"]["original_filename"]
        certification = certify_artwork(source_path).to_dict()
        if not certification["valid"]:
            raise ValueError("The replacement artwork did not pass certification")
        upsert_artwork_certification(artwork_code, certification)
        master = build_print_master(artwork, source_path)
        upsert_artwork_file(
            artwork_code=artwork_code, role="print_master",
            relative_path=master.relative_path, stored_filename=master.master_filename,
            original_filename=original_filename,
        )
        master_path = workspace / master.relative_path
        upsert_print_master_certification(artwork_code, certify_artwork(master_path).to_dict())
        _generate_required_ratios(artwork, overwrite=True)
        saved_templates = {
            row["slot_key"]: row["template_key"]
            for row in get_artwork_mockup_templates(artwork_code)
        }
        saved_scene_key = saved_templates.get("room", "")
        saved_scene = None
        saved_scene_id = saved_scene_key.removeprefix("scene:")
        if saved_scene_key.startswith("scene:") and saved_scene_id.isdigit():
            saved_scene = get_mockup_scene(int(saved_scene_id))
            if saved_scene is not None and not saved_scene["active"]:
                saved_scene = None
        mockups = generate_mockups(
            artwork=dict(artwork), source_path=master_path,
            output_folder=workspace / "03 Mockups", template_key=DEFAULT_TEMPLATE_PACK,
        )
        for result in mockups:
            upsert_artwork_file(
                artwork_code=artwork_code, role=result["role"],
                relative_path=str(result["path"].relative_to(workspace)),
                stored_filename=result["stored_filename"], original_filename=result["original_filename"],
            )
        if saved_scene is not None:
            scene_result = generate_scene_mockup(
                artwork=dict(artwork), source_path=master_path,
                scene_path=MOCKUP_SCENES_DIR / saved_scene["image_path"],
                scene=dict(saved_scene), output_folder=workspace / "03 Mockups",
            )
            upsert_artwork_file(
                artwork_code=artwork_code, role=scene_result["role"],
                relative_path=str(scene_result["path"].relative_to(workspace)),
                stored_filename=scene_result["stored_filename"],
                original_filename=scene_result["original_filename"],
            )
        template_assignments = {
            slot: DEFAULT_TEMPLATE_PACK for slot in GENERATED_SLOTS
        }
        if saved_scene is not None:
            template_assignments["room"] = saved_scene_key
        save_artwork_mockup_templates(
            artwork_code, template_assignments
        )
        assignments = {row["role"]: row for row in get_artwork_file_assignments(artwork_code)}
        files_by_role = {
            role: resolve_assigned_file(artwork, assignment)
            for role, assignment in assignments.items() if role.startswith("ratio:")
        }
        update_printify_product_artwork(
            api, product_id=listing["printify_product_id"], listing=listing,
            files_by_role=files_by_role,
        )
        record_publishing_recovery(
            listing_id, "update_printify_ready",
            "The new artwork is saved in Printify and is ready to publish.",
        )
        set_artwork_production_flags(
            artwork_code, print_master_ready=True, ratio_exports_ready=True,
            mockups_ready=True, original_approved=True,
        )
        api.publish_product(listing["printify_product_id"])
        mark_printify_publish_requested(listing_id)
        record_publishing_recovery(
            listing_id, "update_waiting_for_printify",
            "Printify is publishing the new artwork. The upload will not be repeated.",
        )
        wait_for_product_unlock(api, listing["printify_product_id"])
        record_publishing_recovery(
            listing_id, "update_waiting_for_etsy",
            "Printify finished. ShangooliOS is applying the final Etsy details.",
        )
        result = sync_etsy_listing(get_listing(listing_id))
        mark_etsy_synced(listing_id, result.get("state", ""))
        record_publishing_recovery(
            listing_id, "update_complete",
            "Printify published the replacement and Etsy has the final ShangooliOS details.",
        )
    except PrintifyPublishPending as failure:
        record_publishing_recovery(
            listing_id, "update_waiting_for_printify", str(failure)
        )
        return RedirectResponse(
            f"/artworks/{artwork_code.upper()}?step=publish&update_pending=1",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ValueError, PrintifyAPIError, EtsyAPIError) as failure:
        checkpoint = get_listing(listing_id)["publishing_recovery_stage"]
        if checkpoint in {
            "update_printify_ready", "update_waiting_for_printify", "update_waiting_for_etsy"
        }:
            record_publishing_recovery(listing_id, checkpoint, f"Paused safely: {failure}")
            return RedirectResponse(
                f"/artworks/{artwork_code.upper()}?step=publish&update_pending=1",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    finally:
        if upload:
            upload.file.close()
    return RedirectResponse(
        f"/artworks/{artwork_code.upper()}?step=publish&updated_everywhere=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/listings/{listing_id}/update-everywhere/recover")
def recover_artwork_update_everywhere(artwork_code: str, listing_id: int):
    artwork = get_artwork(artwork_code)
    listing = get_listing(listing_id)
    if artwork is None or listing is None or listing["artwork_code"] != artwork_code.upper():
        raise HTTPException(status_code=404, detail="Artwork listing not found")
    api = PrintifyAPI.from_env()
    if api is None:
        raise HTTPException(status_code=400, detail="Connect Printify before continuing")
    stage = listing["publishing_recovery_stage"] or ""
    try:
        if stage == "update_printify_ready":
            api.publish_product(listing["printify_product_id"])
            mark_printify_publish_requested(listing_id)
            record_publishing_recovery(
                listing_id, "update_waiting_for_printify",
                "Printify is publishing the new artwork. The upload was not repeated.",
            )
            stage = "update_waiting_for_printify"
        if stage == "update_waiting_for_printify":
            wait_for_product_unlock(api, listing["printify_product_id"])
            record_publishing_recovery(
                listing_id, "update_waiting_for_etsy",
                "Printify finished. ShangooliOS is applying the final Etsy details.",
            )
            stage = "update_waiting_for_etsy"
        if stage == "update_waiting_for_etsy":
            result = sync_etsy_listing(get_listing(listing_id))
            mark_etsy_synced(listing_id, result.get("state", ""))
            record_publishing_recovery(
                listing_id, "update_complete",
                "Printify published the replacement and Etsy has the final ShangooliOS details.",
            )
    except PrintifyPublishPending as failure:
        record_publishing_recovery(
            listing_id, "update_waiting_for_printify", str(failure)
        )
    except (ValueError, PrintifyAPIError, EtsyAPIError) as failure:
        current = get_listing(listing_id)["publishing_recovery_stage"] or stage
        record_publishing_recovery(listing_id, current, f"Paused safely: {failure}")
    completed = get_listing(listing_id)["publishing_recovery_stage"] == "update_complete"
    return RedirectResponse(
        f"/artworks/{artwork_code.upper()}?step=publish&{'updated_everywhere' if completed else 'update_pending'}=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/print-master/build")
def create_print_master_from_source(artwork_code: str):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    assignments = {
        row["role"]: row
        for row in get_artwork_file_assignments(artwork_code)
    }
    source_assignment = assignments.get("source")
    if source_assignment is None:
        raise HTTPException(status_code=400, detail="Upload source artwork first")

    try:
        source_path = resolve_assigned_file(artwork, source_assignment)
        master = build_print_master(artwork, source_path)
        upsert_artwork_file(
            artwork_code=artwork_code,
            role="print_master",
            relative_path=master.relative_path,
            stored_filename=master.master_filename,
            original_filename=source_assignment["original_filename"],
        )
        set_artwork_production_flags(artwork_code, print_master_ready=True)
        master_path = get_artwork_folder(artwork) / master.relative_path
        upsert_print_master_certification(
            artwork_code,
            certify_artwork(master_path).to_dict(),
        )
        _generate_required_ratios(artwork, overwrite=True)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=print&master_built=1",
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
        workspace = get_artwork_folder(artwork)
        master_path = workspace / saved["relative_path"]
        certification = certify_artwork(master_path).to_dict()
        upsert_print_master_certification(artwork_code, certification)        
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
        url=f"/artworks/{artwork_code.upper()}?step=print&file_saved=master",
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
        url=f"/artworks/{artwork_code.upper()}?step=print&file_saved=ratio",
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
def generate_mockups_post(artwork_code: str, template_key: str = Form(DEFAULT_TEMPLATE_PACK)):
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
            template_key=template_key,
        )
        for result in results:
            upsert_artwork_file(
                artwork_code=artwork_code,
                role=result["role"],
                relative_path=str(result["path"].relative_to(workspace)),
                stored_filename=result["stored_filename"],
                original_filename=result["original_filename"],
            )
        save_artwork_mockup_templates(
            artwork_code,
            {slot_key: template_key for slot_key in GENERATED_SLOTS},
        )
        set_artwork_production_flags(artwork_code, mockups_ready=False)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=mockups&mockups_generated=8&template_pack={template_key}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/mockups/scene")
def generate_scene_mockup_post(artwork_code: str, scene_id: int = Form(...)):
    artwork = get_artwork(artwork_code)
    scene = get_mockup_scene(scene_id)
    if artwork is None or scene is None or not scene["active"]:
        raise HTTPException(status_code=404, detail="Artwork or mockup scene not found")
    production = get_artwork_production(artwork_code)
    if scene["orientation"] not in {"any", production["orientation"]}:
        raise HTTPException(
            status_code=400, detail="Choose a scene matching the artwork orientation"
        )
    assignments = {
        row["role"]: row for row in get_artwork_file_assignments(artwork_code)
    }
    source_assignment = assignments.get("print_master") or assignments.get("source")
    if source_assignment is None:
        raise HTTPException(status_code=400, detail="Upload artwork before generating a mockup")
    try:
        workspace = get_artwork_folder(artwork)
        result = generate_scene_mockup(
            artwork=dict(artwork),
            source_path=resolve_assigned_file(artwork, source_assignment),
            scene_path=MOCKUP_SCENES_DIR / scene["image_path"],
            scene=dict(scene), output_folder=workspace / "03 Mockups",
        )
        upsert_artwork_file(
            artwork_code=artwork_code, role=result["role"],
            relative_path=str(result["path"].relative_to(workspace)),
            stored_filename=result["stored_filename"],
            original_filename=result["original_filename"],
        )
        save_artwork_mockup_template(artwork_code, "room", f"scene:{scene_id}")
        set_artwork_production_flags(artwork_code, mockups_ready=False)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(
        f"/artworks/{artwork_code.upper()}?step=mockups&scene_mockup_generated=1",
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
        url=f"/artworks/{artwork_code.upper()}?step=mockups&mockup_saved={slot_key}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/mockups/{slot_key}/generate")
async def generate_one_listing_image_post(artwork_code: str, slot_key: str, request: Request):
    artwork = get_artwork(artwork_code)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    if slot_key not in GENERATED_SLOTS:
        raise HTTPException(status_code=400, detail="Invalid listing image slot")

    form = await request.form()
    template_key = str(form.get(f"{slot_key}_template_key") or DEFAULT_TEMPLATE_PACK)

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
            template_key=template_key,
        )
        upsert_artwork_file(
            artwork_code=artwork_code,
            role=result["role"],
            relative_path=str(result["path"].relative_to(workspace)),
            stored_filename=result["stored_filename"],
            original_filename=result["original_filename"],
        )
        save_artwork_mockup_template(artwork_code, slot_key, template_key)
        set_artwork_production_flags(artwork_code, mockups_ready=False)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=mockups&listing_image_generated={slot_key}&template_pack={template_key}",
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
        url=f"/artworks/{artwork_code.upper()}?step=mockups&mockup_settings_saved=1",
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
        url=f"/artworks/{artwork_code.upper()}?step=print&ratio_review_saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/validate")
def validate_artwork_production(artwork_code: str):
    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=details&validated=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/artworks/{artwork_code}/workspace/refresh")
def refresh_artwork_workspace(artwork_code: str):
    artwork = get_artwork(artwork_code)

    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")

    refresh_workspace(artwork)

    return RedirectResponse(
        url=f"/artworks/{artwork_code.upper()}?step=source&workspace_refreshed=1",
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
