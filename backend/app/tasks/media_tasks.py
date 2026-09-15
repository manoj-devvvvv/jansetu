"""
Media processing tasks for the core AI pipeline.

Implements voice transcription (Whisper/Groq) and text formalization (Gemini).
"""

from app.tasks.celery_app import celery_app
from app.db.sync_session import get_sync_db
from sqlalchemy import text as sa_text
from uuid import UUID
import logging
from app.core.nlp import transcribe_audio, formalize_text

logger = logging.getLogger(__name__)

@celery_app.task(name="media.process_nlp_pipeline", bind=True, max_retries=3)
def process_nlp_pipeline(self, complaint_id: str):
    """
    Executes the NLP pipeline for a complaint:
    1. Transcribe audio if input_mode is 'voice'
    2. Formalize raw text (and detect language) using LLM
    3. Update Complaint and ComplaintProcessingStatus
    """
    db = get_sync_db()
    try:
        cid = UUID(complaint_id)
        
        # Fetch complaint
        q_complaint = sa_text("""
            SELECT id, input_mode, voice_audio_url, raw_text
            FROM complaints
            WHERE id = :cid
        """)
        complaint = db.execute(q_complaint, {"cid": cid}).fetchone()
        
        if not complaint:
            logger.error(f"Complaint {cid} not found for NLP processing.")
            return {"status": "error", "error": "Complaint not found"}

        # Fetch status
        q_status = sa_text("""
            SELECT transcription_status, formalization_status
            FROM complaint_processing_status
            WHERE complaint_id = :cid
        """)
        status_row = db.execute(q_status, {"cid": cid}).fetchone()
        
        if not status_row:
            logger.error(f"ComplaintProcessingStatus for {cid} not found.")
            return {"status": "error", "error": "Status row not found"}

        current_raw_text = complaint.raw_text
        transcription_conf = None

        # --- STEP 1: TRANSCRIPTION ---
        if complaint.input_mode == 'voice' and status_row.transcription_status == 'pending':
            logger.info(f"Starting transcription for {cid}")
            db.execute(sa_text("""
                UPDATE complaint_processing_status
                SET transcription_status = 'processing', updated_at = now()
                WHERE complaint_id = :cid
            """), {"cid": cid})
            db.commit()
            
            if not complaint.voice_audio_url:
                raise ValueError("Voice mode selected but no audio URL found")
                
            text, conf = transcribe_audio(complaint.voice_audio_url)
            
            if text is None:
                raise Exception("Transcription failed (API returned None)")
                
            current_raw_text = text
            transcription_conf = conf
            
            db.execute(sa_text("""
                UPDATE complaints
                SET raw_text = :text, transcription_confidence = :conf, updated_at = now()
                WHERE id = :cid
            """), {"text": current_raw_text, "conf": transcription_conf, "cid": cid})
            
            db.execute(sa_text("""
                UPDATE complaint_processing_status
                SET transcription_status = 'completed', updated_at = now()
                WHERE complaint_id = :cid
            """), {"cid": cid})
            db.commit()

        # --- STEP 2: FORMALIZATION ---
        if current_raw_text and status_row.formalization_status == 'pending':
            logger.info(f"Starting formalization for {cid}")
            db.execute(sa_text("""
                UPDATE complaint_processing_status
                SET formalization_status = 'processing', updated_at = now()
                WHERE complaint_id = :cid
            """), {"cid": cid})
            db.commit()
            
            form_text, lang = formalize_text(current_raw_text)
            
            if form_text is None:
                raise Exception("Formalization failed (API returned None)")
                
            db.execute(sa_text("""
                UPDATE complaints
                SET formalized_text = :form_text, detected_language = :lang, updated_at = now()
                WHERE id = :cid
            """), {"form_text": form_text, "lang": lang, "cid": cid})
            
            db.execute(sa_text("""
                UPDATE complaint_processing_status
                SET formalization_status = 'completed', updated_at = now()
                WHERE complaint_id = :cid
            """), {"cid": cid})
            db.commit()

        logger.info(f"NLP Pipeline completed successfully for {cid}")
        
        # --- STEP 3: TRIGGER CLUSTERING ---
        try:
            from app.tasks.complaint_tasks import process_complaint_clustering
            process_complaint_clustering.delay(str(cid))
            logger.info(f"Triggered clustering for {cid}")
        except Exception as e:
            logger.exception(f"Failed to trigger clustering for {cid}: {e}")
            
        return {"status": "success", "complaint_id": str(cid)}
        
    except Exception as exc:
        db.rollback()
        logger.exception(f"Error in NLP pipeline for {complaint_id}")
        
        # Mark as failed in DB before retrying
        try:
            db.execute(sa_text("""
                UPDATE complaint_processing_status
                SET transcription_status = CASE WHEN transcription_status = 'processing' THEN 'failed'::ai_processing_status ELSE transcription_status END,
                    formalization_status = CASE WHEN formalization_status = 'processing' THEN 'failed'::ai_processing_status ELSE formalization_status END,
                    updated_at = now()
                WHERE complaint_id = :cid
            """), {"cid": UUID(complaint_id)})
            db.commit()
        except:
            db.rollback()
            
        raise self.retry(exc=exc, countdown=60)
        
    finally:
        db.close()
