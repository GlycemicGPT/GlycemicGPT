---
title: Kubernetes External Access & TLS
description: Exposing a Kubernetes-deployed GlycemicGPT to the internet with TLS.
---

# Kubernetes External Access & TLS Setup

This guide covers exposing GlycemicGPT to the internet with TLS encryption, which is required for the mobile app to connect securely.

## Prerequisites

- A Kubernetes cluster with an ingress controller (nginx-ingress or traefik)
- A domain name pointing to your cluster's external IP
- kubectl configured for your cluster

## 1. Install cert-manager

cert-manager automates TLS certificate provisioning from Let's Encrypt.

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml
kubectl wait --for=condition=Available deployment/cert-manager -n cert-manager --timeout=120s
```

## 2. Create ClusterIssuer

Edit `k8s/base/cert-manager-issuer.yaml` and set your email address, then apply:

```bash
kubectl apply -f k8s/base/cert-manager-issuer.yaml
```

## 3. Configure DNS

Point your domain to the cluster's external IP:

```
glycemicgpt.yourdomain.com  A  <your-cluster-external-ip>
```

If using a cloud provider with a load balancer, use a CNAME record pointing to the load balancer hostname.

## 4. Update Ingress

Edit `k8s/base/ingress.yaml` and replace `glycemicgpt.local` with your domain in both the `rules[].host` and `tls[].hosts[]` fields.

```bash
kubectl apply -f k8s/base/ingress.yaml
```

cert-manager will automatically provision a TLS certificate from Let's Encrypt.

## 5. Verify

```bash
# Check certificate status
kubectl get certificate -n glycemicgpt

# Test HTTPS
curl https://glycemicgpt.yourdomain.com/health
```

## Mobile App Configuration

In the mobile app Settings screen, set the Server URL to:

```
https://glycemicgpt.yourdomain.com
```

The app enforces HTTPS in release builds. HTTP is only allowed in debug builds for local development.

## Self-Signed Certificates (Alternative)

For internal/homelab setups without a public domain, you can use self-signed certificates:

```bash
# Generate self-signed cert
openssl req -x509 -newkey rsa:4096 -keyout tls.key -out tls.crt -days 365 -nodes \
  -subj "/CN=glycemicgpt.local"

# Create K8s secret
kubectl create secret tls glycemicgpt-tls \
  --cert=tls.crt --key=tls.key \
  -n glycemicgpt
```

Remove the `cert-manager.io/cluster-issuer` annotation from the ingress when using self-signed certs.

Note: The mobile app's network security config allows user-installed CAs in debug builds. For release builds with self-signed certs, you would need to add the CA to the app's trust store.
