# AI Dropship Autopilot

Production-oriented AI dropshipping platform. The app uses real APIs only: OpenAI for intelligence, CJdropshipping for supplier/product/order operations, and WooCommerce for the storefront.

## Stack
- FastAPI + SQLite
- Vanilla responsive frontend
- OpenAI Responses API
- CJdropshipping API v2
- WooCommerce REST API v3
- Background polling for supplier/order sync

## Required environment
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini
ADMIN_TOKEN=
CJ_ACCESS_TOKEN=
WC_URL=
WC_CONSUMER_KEY=
WC_CONSUMER_SECRET=
STORE_CURRENCY=USD
PUBLIC_BASE_URL=

No fake products, prices, inventory, orders, sales or analytics are generated. If a provider is not configured, the UI shows the provider as disconnected and the operation fails safely.

## Run
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

Open / for the storefront and /admin for operations.

WooCommerce is open-source, but production hosting, a domain, payment processing, and OpenAI usage are not universally free. CJ also requires an account/API credentials for live fulfillment.
