"""业务路由汇总：交账包等专用路由需在通用动态路由之前注册。"""
from __future__ import annotations

from app.routers.fund_package import router as fund_package_router
from app.routers.resource import router as resource_router

ROUTERS = [fund_package_router, resource_router]
