-- 0019_frame_caption_content_type.sql
-- Video frame analysis (app/multimodal/video_processor.py) stores one
-- extracted_information row per sampled frame with
-- content_type='frame_caption'. Databases created before that feature
-- have a CHECK constraint (0010) that rejects it, so every video
-- upload failed on Postgres. 0010 now includes it for fresh installs;
-- this upgrades existing databases. Guarded so re-running it on every
-- startup (see PostgresMetadataRepository._apply_migrations) is a no-op.

DO $$
DECLARE
    constraint_definition TEXT;
BEGIN
    SELECT pg_get_constraintdef(oid) INTO constraint_definition
    FROM pg_constraint
    WHERE conname = 'extracted_information_content_type_check';

    IF constraint_definition IS NOT NULL AND position('frame_caption' IN constraint_definition) = 0 THEN
        ALTER TABLE extracted_information DROP CONSTRAINT extracted_information_content_type_check;
        ALTER TABLE extracted_information ADD CONSTRAINT extracted_information_content_type_check
            CHECK (content_type IN ('text', 'ocr_text', 'transcript', 'caption', 'frame_caption'));
    END IF;
END $$;
