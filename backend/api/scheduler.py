"""定时任务 CRUD、执行历史与系统级唤醒委托入口。"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.maa_worker import execution
from backend.models.scheduler import (
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
)
from backend.runtime import app_state

router = APIRouter()


class NativeDispatchRequest(BaseModel):
    task_id: str


@router.post("/api/internal/scheduler/native-dispatch")
async def native_dispatch(payload: NativeDispatchRequest):
    """冷启动委托入口：由系统级唤醒触发的二次进程将任务移交给本实例"""
    task = await app_state.scheduler_manager.get_task(payload.task_id)
    if task is None:
        return JSONResponse(
            status_code=404,
            content={"status": "failed", "message": "任务不存在"},
        )
    if not task.enabled or not task.wakeup_enabled:
        return JSONResponse(
            status_code=409,
            content={"status": "failed", "message": "任务未启用系统级唤醒"},
        )
    admission = await execution.submit_scheduled(app_state, task, origin="native")
    if admission.accepted:
        return {"status": "success", "run_id": admission.run_id, "skip_status": None}
    return JSONResponse(
        status_code=409,
        content={
            "status": "failed",
            "message": "入场被拒",
            "skip_status": admission.skip_status,
        },
    )


@router.get("/api/scheduler/tasks")
async def get_scheduler_tasks():
    """获取所有定时任务"""
    try:
        tasks = await app_state.scheduler_manager.get_all_tasks()
        return {"status": "success", "tasks": [task.model_dump() for task in tasks]}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"获取调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@router.post("/api/scheduler/tasks")
async def create_scheduler_task(task_create: ScheduledTaskCreate):
    """创建定时任务"""
    try:
        task = await app_state.scheduler_manager.create_task(task_create)
        return {"status": "success", "task": task.model_dump()}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"创建调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@router.put("/api/scheduler/tasks/{task_id}")
async def update_scheduler_task(task_id: str, task_update: ScheduledTaskUpdate):
    """更新定时任务"""
    try:
        task = await app_state.scheduler_manager.update_task(task_id, task_update)
        if task is None:
            msg = "任务不存在"
            app_state.send_log(msg)
            return {"status": "failed", "message": msg}
        return {"status": "success", "task": task.model_dump()}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"更新调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@router.delete("/api/scheduler/tasks/{task_id}")
async def delete_scheduler_task(task_id: str):
    """删除定时任务"""
    try:
        success = await app_state.scheduler_manager.delete_task(task_id)
        if success:
            return {"status": "success"}
        msg = "任务不存在"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"删除调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@router.post("/api/scheduler/tasks/{task_id}/pause")
async def pause_scheduler_task(task_id: str):
    """暂停定时任务"""
    try:
        success = await app_state.scheduler_manager.pause_task(task_id)
        if success:
            return {"status": "success"}
        msg = "任务不存在"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"暂停调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@router.post("/api/scheduler/tasks/{task_id}/resume")
async def resume_scheduler_task(task_id: str):
    """恢复定时任务"""
    try:
        success = await app_state.scheduler_manager.resume_task(task_id)
        if success:
            return {"status": "success"}
        msg = "任务不存在"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"恢复调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@router.get("/api/scheduler/executions")
async def get_scheduler_executions(limit: int = 50):
    """获取执行历史"""
    try:
        executions = await app_state.scheduler_manager.get_executions(limit)
        return {
            "status": "success",
            "executions": [exec.model_dump() for exec in executions],
        }
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"获取调度执行历史失败: {msg}")
        return {"status": "failed", "message": msg}
