ALTER TABLE urls 
ADD COLUMN custom_alias TEXT;
ALTER TABLE urls 
ADD COLUMN expires_at TIMESTAMP;
ALTER TABLE urls 
ADD COLUMN clicks_by_date TEXT;