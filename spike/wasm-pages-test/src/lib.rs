use gloo_net::http::Request;
use leptos::prelude::*;
use serde::Deserialize;
use wasm_bindgen::{prelude::*, JsCast};
use wasm_bindgen_futures::spawn_local;

#[derive(Debug, Deserialize)]
struct IslandData {
    message: String,
}

fn set_status(status: &str) {
    if let Some(document) = web_sys::window().and_then(|window| window.document()) {
        if let Some(status_el) = document.get_element_by_id("spike-status") {
            status_el.set_text_content(Some(status));
        }
        document.set_title(status);
    }
}

#[component]
fn Island() -> impl IntoView {
    let (count, set_count) = signal(0_i32);
    let (message, set_message) = signal(String::from("fetch pending"));

    Effect::new(move |_| {
        spawn_local(async move {
            match Request::get("./island-data.json").send().await {
                Ok(response) if response.ok() => match response.json::<IslandData>().await {
                    Ok(data) => {
                        set_message.set(data.message);
                        set_status("SPIKE_PASS");
                    }
                    Err(err) => set_status(&format!("SPIKE_FAIL: parsing island-data.json: {err}")),
                },
                Ok(response) => set_status(&format!(
                    "SPIKE_FAIL: fetch island-data.json returned HTTP {}",
                    response.status()
                )),
                Err(err) => set_status(&format!("SPIKE_FAIL: fetching island-data.json: {err}")),
            }
        });
    });

    view! {
        <section aria-label="Leptos WASM island">
            <h1>"leptos island mounted OK"</h1>
            <p>"same-origin fetch: " <strong>{move || message.get()}</strong></p>
            <button type="button" on:click=move |_| set_count.update(|value| *value += 1)>
                "counter: " {move || count.get()}
            </button>
        </section>
    }
}

#[wasm_bindgen(start)]
pub fn main() {
    console_error_panic_hook::set_once();
    set_status("SPIKE_FAIL: Leptos mounted before fetch completed");

    if let Some(document) = web_sys::window().and_then(|window| window.document()) {
        if let Some(root) = document
            .get_element_by_id("island-root")
            .and_then(|element| element.dyn_into::<web_sys::HtmlElement>().ok())
        {
            mount_to(root, || view! { <Island /> }).forget();
            return;
        }
    }

    set_status("SPIKE_FAIL: missing #island-root");
}
