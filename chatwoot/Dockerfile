FROM chatwoot/chatwoot:v4.13.0-ce

RUN sed -i 's/ActsAsTaggableOn::Taggable::Cache.included(Conversation)/# Cache.included removed for compatibility/' /app/db/migrate/20231211010807_add_cached_labels_list.rb
