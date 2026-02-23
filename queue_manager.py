import asyncio
import io
import logging
import time
from functools import partial
from drive_service import get_drive_service, upload_file, GoogleAuthError
from config import DRIVE_FOLDER_ID

logger = logging.getLogger(__name__)

class QueueManager:
    def __init__(self, application):
        self.application = application
        self.queue = asyncio.Queue()
        self.is_processing = False
        self.paused = False
        self.worker_task = None
        self.last_update_time = {}

    async def add_job(self, update, context, file_info):
        """Adds a job to the queue."""
        if self.paused:
            await update.message.reply_text("🛑 The bot is currently paused by an admin. New tasks are not accepted.")
            return

        status_message = await update.message.reply_text("Queued... Waiting for turn.")
        job = {
            'update': update,
            'context': context,
            'file_info': file_info,
            'status_message': status_message,
            'start_time': time.time(),
            'user_id': update.effective_user.id
        }
        await self.queue.put(job)
        
        # If not processing, start the worker
        if not self.is_processing:
            self.worker_task = asyncio.create_task(self.worker())
        else:
            # Show queue position
            await self.update_queue_status()

    async def pause_bot(self):
        """Pauses the bot, clears the queue, and cancels the current task."""
        self.paused = True
        
        # Clear the queue and notify users
        cancelled_count = 0
        while not self.queue.empty():
            job = await self.queue.get()
            try:
                await job['status_message'].edit_text("🛑 This task was cancelled because the bot was paused by an admin.")
            except Exception:
                pass
            self.queue.task_done()
            cancelled_count += 1
            
        # Cancel the current worker task
        if self.worker_task and not self.worker_task.done():
            self.worker_task.cancel()
            
        return cancelled_count

    async def resume_bot(self):
        """Resumes the bot."""
        self.paused = False

    async def update_queue_status(self):
        """Updates the status of all queued jobs with their position."""
        temp_list = []
        while not self.queue.empty():
            temp_list.append(await self.queue.get())
        
        for i, job in enumerate(temp_list):
            try:
                position = i + 1
                await job['status_message'].edit_text(f"Queued... Position in line: {position}")
            except Exception:
                pass
            await self.queue.put(job)

    async def worker(self):
        """Background worker to process jobs one by one."""
        self.is_processing = True
        try:
            while not self.queue.empty() and not self.paused:
                job = await self.queue.get()
                try:
                    await self.process_job(job)
                except asyncio.CancelledError:
                    logger.info("Worker task cancelled.")
                    try:
                        await job['status_message'].edit_text("🛑 This task was force-stopped by an admin.")
                    except Exception:
                        pass
                    raise
                except Exception as e:
                    logger.error(f"Error processing job: {e}")
                    try:
                        await job['status_message'].edit_text(f"❌ Error: {str(e)}")
                    except Exception:
                        pass
                finally:
                    self.queue.task_done()
                    # Update remaining jobs' positions
                    await self.update_queue_status()
        except asyncio.CancelledError:
            logger.info("Worker loop cancelled.")
        finally:
            self.is_processing = False
            self.worker_task = None

    async def process_job(self, job):
        """Processes a single upload job."""
        update = job['update']
        context = job['context']
        file_info = job['file_info']
        status_message = job['status_message']
        
        file_name = file_info['name']
        mime_type = file_info['mime_type']
        tg_file = file_info['file']

        await status_message.edit_text(f"Downloading {file_name}...")
        
        # Download with progress
        file_content = io.BytesIO()
        await tg_file.download_to_memory(file_content)
        file_content.seek(0)
        
        await status_message.edit_text(f"Uploading {file_name} to Google Drive...")

        try:
            service = get_drive_service()
            loop = asyncio.get_running_loop()
            
            async def progress_callback_async(progress):
                percent = int(progress * 100)
                message_id = status_message.message_id
                now = time.time()
                if message_id not in self.last_update_time or now - self.last_update_time[message_id] > 2:
                    self.last_update_time[message_id] = now
                    try:
                        filled = int(percent / 10)
                        bar = "█" * filled + "░" * (10 - filled)
                        await status_message.edit_text(f"Uploading {file_name}\n[{bar}] {percent}%")
                    except Exception:
                        pass

            def progress_callback_sync(p):
                asyncio.run_coroutine_threadsafe(progress_callback_async(p), loop)

            def check_cancelled():
                return self.paused

            # Use partial to pass progress_callback_sync explicitly
            upload_func = partial(
                upload_file,
                service, 
                file_name, 
                file_content, 
                DRIVE_FOLDER_ID, 
                mime_type=mime_type,
                progress_callback=progress_callback_sync,
                check_cancelled=check_cancelled
            )

            file_id = await loop.run_in_executor(None, upload_func)

            # Final update
            await asyncio.sleep(0.5)
            await status_message.edit_text(f"✅ Successfully uploaded!\nFile: `{file_name}`\nID: `{file_id}`", parse_mode='Markdown')
            
        except Exception as e:
            if "cancelled by admin" in str(e).lower():
                logger.info(f"Upload of {file_name} cancelled by admin.")
                # The worker will handle the status message update if it was a CancelledError
                # but here it's an Exception raised within the executor.
                raise asyncio.CancelledError() from e
            if isinstance(e, GoogleAuthError):
                await status_message.edit_text(f"❌ **Drive Auth Error:**\n`{str(e)}`\n\nUse /reauth to fix this.", parse_mode='Markdown')
            else:
                await status_message.edit_text(f"❌ **Upload failed:**\n`{str(e)}`", parse_mode='Markdown')
        finally:
            self.last_update_time.pop(status_message.message_id, None)
