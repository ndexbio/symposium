{{/* Every resource is named after the release: `helm install symposium-data …` gives
deploy/symposium-data and svc/symposium-data. */}}
{{- define "symposium.name" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "symposium.selectorLabels" -}}
app.kubernetes.io/name: symposium-data
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "symposium.labels" -}}
{{ include "symposium.selectorLabels" . }}
app.kubernetes.io/version: {{ include "symposium.tag" . | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "symposium.tag" -}}
{{- .Values.image.tag | default .Chart.AppVersion -}}
{{- end -}}

{{- define "symposium.image" -}}
{{- printf "%s:%s" .Values.image.repository (include "symposium.tag" .) -}}
{{- end -}}

{{/* The Secret holding admin_pub_<handle>.key: one made elsewhere, or the chart's own. */}}
{{- define "symposium.adminKeySecret" -}}
{{- .Values.adminKey.existingSecret | default (printf "%s-admin-key" (include "symposium.name" .)) -}}
{{- end -}}

{{/* Changes whenever the chart's admin key does, so the pod restarts and reads it. */}}
{{- define "symposium.adminKeyChecksum" -}}
{{- printf "%s\n%s\n%s" .Values.adminKey.handle .Values.adminKey.publicKey .Values.adminKey.existingSecret | sha256sum -}}
{{- end -}}

{{/* Settings that only make sense together, refused with a message saying what to set. */}}
{{- define "symposium.validate" -}}
{{- $key := .Values.adminKey -}}
{{- if and $key.existingSecret (or $key.handle $key.publicKey) -}}
{{- fail "adminKey: set either existingSecret, or handle and publicKey, not both" -}}
{{- end -}}
{{- if and $key.handle (not $key.publicKey) -}}
{{- fail "adminKey.handle is set without its key: add --set-file adminKey.publicKey=<path to admin_pub_<handle>.key>" -}}
{{- end -}}
{{- if and $key.publicKey (not $key.handle) -}}
{{- fail "adminKey.publicKey is set without its handle: set adminKey.handle, the <handle> in admin_pub_<handle>.key" -}}
{{- end -}}
{{- if eq .Values.expose.mode "gateway" -}}
{{- if not .Values.expose.gateway.parentRefs -}}
{{- fail "expose.mode=gateway needs expose.gateway.parentRefs: the Gateway to attach to, e.g. [{name: public, namespace: gateways}]" -}}
{{- end -}}
{{- if not (.Capabilities.APIVersions.Has "gateway.networking.k8s.io/v1/HTTPRoute") -}}
{{- fail "expose.mode=gateway, but this cluster has no Gateway API (gateway.networking.k8s.io/v1 HTTPRoute): install it, or use expose.mode=ingress" -}}
{{- end -}}
{{- end -}}
{{- if and (eq .Values.expose.mode "ingress") (not .Values.expose.ingress.host) -}}
{{- fail "expose.mode=ingress needs expose.ingress.host, e.g. data.example.org" -}}
{{- end -}}
{{- end -}}
