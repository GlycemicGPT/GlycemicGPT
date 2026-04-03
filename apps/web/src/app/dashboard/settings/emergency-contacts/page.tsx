"use client";

/**
 * Story 6.5: Emergency Contact Configuration
 *
 * CRUD page for managing emergency contacts used in alert escalation.
 * Max 3 contacts per user, each with name, Telegram username, and priority.
 *
 * Accessibility: labeled inputs, aria-describedby, focus-visible rings.
 */

import { useState, useEffect, useCallback } from "react";
import {
  Users,
  Plus,
  Loader2,
  AlertTriangle,
  Check,
  Trash2,
  Pencil,
  ArrowLeft,
  X,
} from "lucide-react";
import clsx from "clsx";
import {
  getEmergencyContacts,
  createEmergencyContact,
  updateEmergencyContact,
  deleteEmergencyContact,
  type EmergencyContact,
} from "@/lib/api";
import { OfflineBanner } from "@/components/ui/offline-banner";

const MAX_CONTACTS = 3;

interface ContactFormData {
  name: string;
  telegram_username: string;
  priority: "primary" | "secondary";
}

const EMPTY_FORM: ContactFormData = {
  name: "",
  telegram_username: "",
  priority: "primary",
};

export default function EmergencyContactsPage() {
  const [contacts, setContacts] = useState<EmergencyContact[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isOffline, setIsOffline] = useState(false);

  // Form state
  const [formData, setFormData] = useState<ContactFormData>({ ...EMPTY_FORM });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const fetchContacts = useCallback(async () => {
    try {
      setError(null);
      const data = await getEmergencyContacts();
      setContacts(data.contacts);
      setIsOffline(false);
    } catch (err) {
      if (!(err instanceof Error && err.message.includes("401"))) {
        setIsOffline(true);
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchContacts();
  }, [fetchContacts]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);
    setSuccess(null);

    try {
      if (editingId) {
        await updateEmergencyContact(editingId, {
          name: formData.name,
          telegram_username: formData.telegram_username,
          priority: formData.priority,
        });
        setSuccess("Contact updated successfully");
      } else {
        await createEmergencyContact(formData);
        setSuccess("Contact added successfully");
      }

      setFormData({ ...EMPTY_FORM });
      setEditingId(null);
      setShowForm(false);
      await fetchContacts();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to save contact"
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleEdit = (contact: EmergencyContact) => {
    setFormData({
      name: contact.name,
      telegram_username: contact.telegram_username,
      priority: contact.priority,
    });
    setEditingId(contact.id);
    setShowForm(true);
    setError(null);
    setSuccess(null);
  };

  const handleDelete = async (contactId: string) => {
    if (!window.confirm("Remove this emergency contact? This cannot be undone.")) {
      return;
    }

    setDeletingId(contactId);
    setError(null);
    setSuccess(null);

    try {
      await deleteEmergencyContact(contactId);
      setSuccess("Contact removed");
      await fetchContacts();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to delete contact"
      );
    } finally {
      setDeletingId(null);
    }
  };

  const handleCancel = () => {
    setFormData({ ...EMPTY_FORM });
    setEditingId(null);
    setShowForm(false);
    setError(null);
  };

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <a
          href="/dashboard/settings"
          className="flex items-center gap-1 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 mb-2"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Settings
        </a>
        <h1 className="text-2xl font-bold">Emergency Contacts</h1>
        <p className="text-slate-500 dark:text-slate-400">
          Manage contacts for automatic alert escalation via Telegram
        </p>
      </div>

      {/* Offline banner */}
      {isOffline && (
        <OfflineBanner
          onRetry={fetchContacts}
          isRetrying={isLoading}
          message="Unable to connect to server. Contact management is unavailable."
        />
      )}

      {/* Error state */}
      {error && (
        <div
          className="bg-red-500/10 rounded-xl p-4 border border-red-500/20"
          role="alert"
        >
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-red-400 shrink-0" />
            <p className="text-sm text-red-400">{error}</p>
          </div>
        </div>
      )}

      {/* Success state */}
      {success && (
        <div
          className="bg-green-500/10 rounded-xl p-4 border border-green-500/20"
          role="status"
        >
          <div className="flex items-center gap-2">
            <Check className="h-4 w-4 text-green-400 shrink-0" />
            <p className="text-sm text-green-400">{success}</p>
          </div>
        </div>
      )}

      {/* Loading state */}
      {isLoading && (
        <div
          className="bg-white dark:bg-slate-900 rounded-xl p-12 border border-slate-200 dark:border-slate-800 text-center"
          role="status"
          aria-label="Loading emergency contacts"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">Loading contacts...</p>
        </div>
      )}

      {/* Contact list */}
      {!isLoading && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 bg-blue-500/10 rounded-lg">
              <Users className="h-5 w-5 text-blue-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Contacts</h2>
              <p className="text-xs text-slate-500">
                {contacts.length} of {MAX_CONTACTS} contacts configured
              </p>
            </div>
          </div>

          {contacts.length === 0 && !showForm && (
            <div className="text-center py-8">
              <Users className="h-10 w-10 text-slate-600 mx-auto mb-3" />
              <p className="text-slate-500 dark:text-slate-400 mb-1">No emergency contacts yet</p>
              <p className="text-xs text-slate-500">
                Add contacts who can be notified when you&apos;re unresponsive
                to alerts
              </p>
            </div>
          )}

          {contacts.length > 0 && (
            <div className="space-y-3 mb-4">
              {contacts.map((contact) => (
                <div
                  key={contact.id}
                  className="flex items-center justify-between bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-300/50 dark:border-slate-700/50"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-slate-200 truncate">
                        {contact.name}
                      </span>
                      <span
                        className={clsx(
                          "text-xs px-2 py-0.5 rounded-full",
                          contact.priority === "primary"
                            ? "bg-blue-500/20 text-blue-400"
                            : "bg-slate-200 dark:bg-slate-700 text-slate-500 dark:text-slate-400"
                        )}
                      >
                        {contact.priority}
                      </span>
                    </div>
                    <span className="text-xs text-slate-500">
                      @{contact.telegram_username}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 ml-3">
                    <button
                      type="button"
                      onClick={() => handleEdit(contact)}
                      disabled={isOffline}
                      className="p-2 rounded-lg text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
                      aria-label={`Edit ${contact.name}`}
                    >
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(contact.id)}
                      disabled={deletingId === contact.id || isOffline}
                      className="p-2 rounded-lg text-slate-500 dark:text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:opacity-50 disabled:cursor-not-allowed"
                      aria-label={`Delete ${contact.name}`}
                    >
                      {deletingId === contact.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Trash2 className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Add button */}
          {!showForm && contacts.length < MAX_CONTACTS && (
            <button
              type="button"
              onClick={() => {
                setShowForm(true);
                setError(null);
                setSuccess(null);
              }}
              disabled={isOffline}
              title={isOffline ? "Cannot add contacts while disconnected" : undefined}
              className={clsx(
                "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium",
                "bg-blue-600 text-white hover:bg-blue-500",
                "transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              <Plus className="h-4 w-4" />
              Add Contact
            </button>
          )}

          {!showForm && contacts.length >= MAX_CONTACTS && (
            <p className="text-xs text-slate-500">
              Maximum of {MAX_CONTACTS} contacts reached
            </p>
          )}

          {/* Add/Edit form */}
          {showForm && (
            <form onSubmit={handleSubmit} className="space-y-4 mt-4">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-medium text-slate-600 dark:text-slate-300">
                  {editingId ? "Edit Contact" : "Add Contact"}
                </h3>
                <button
                  type="button"
                  onClick={handleCancel}
                  className="p-1 rounded text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                  aria-label="Cancel"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div>
                <label
                  htmlFor="contact-name"
                  className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                >
                  Name
                </label>
                <input
                  id="contact-name"
                  type="text"
                  required
                  maxLength={100}
                  value={formData.name}
                  onChange={(e) =>
                    setFormData({ ...formData, name: e.target.value })
                  }
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-200",
                    "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                    "placeholder:text-slate-500"
                  )}
                  placeholder="e.g. Mom"
                  aria-describedby="name-hint"
                />
                <p id="name-hint" className="text-xs text-slate-500 mt-1">
                  Name of the emergency contact
                </p>
              </div>

              <div>
                <label
                  htmlFor="contact-telegram"
                  className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                >
                  Telegram Username
                </label>
                <div className="flex items-center gap-2">
                  <span className="text-slate-500 dark:text-slate-400 text-sm">@</span>
                  <input
                    id="contact-telegram"
                    type="text"
                    required
                    minLength={5}
                    maxLength={32}
                    value={formData.telegram_username}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        telegram_username: e.target.value,
                      })
                    }
                    className={clsx(
                      "w-full rounded-lg border px-3 py-2 text-sm",
                      "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-200",
                      "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                      "placeholder:text-slate-500"
                    )}
                    placeholder="username"
                    aria-describedby="telegram-hint"
                  />
                </div>
                <p id="telegram-hint" className="text-xs text-slate-500 mt-1">
                  5-32 characters, letters, numbers, and underscores
                </p>
              </div>

              <div>
                <label
                  htmlFor="contact-priority"
                  className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                >
                  Priority
                </label>
                <select
                  id="contact-priority"
                  value={formData.priority}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      priority: e.target.value as "primary" | "secondary",
                    })
                  }
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-200",
                    "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  )}
                  aria-describedby="priority-hint"
                >
                  <option value="primary">Primary</option>
                  <option value="secondary">Secondary</option>
                </select>
                <p id="priority-hint" className="text-xs text-slate-500 mt-1">
                  Primary contacts are notified first during escalation
                </p>
              </div>

              <div className="flex items-center gap-3 pt-2">
                <button
                  type="submit"
                  disabled={isSubmitting || isOffline}
                  title={isOffline ? "Cannot save while disconnected" : undefined}
                  className={clsx(
                    "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                    "bg-blue-600 text-white hover:bg-blue-500",
                    "transition-colors",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                >
                  {isSubmitting ? (
                    <Loader2
                      className="h-4 w-4 animate-spin"
                      aria-hidden="true"
                    />
                  ) : (
                    <Check className="h-4 w-4" aria-hidden="true" />
                  )}
                  {isSubmitting
                    ? "Saving..."
                    : editingId
                      ? "Update Contact"
                      : "Add Contact"}
                </button>
                <button
                  type="button"
                  onClick={handleCancel}
                  disabled={isSubmitting}
                  className={clsx(
                    "px-4 py-2 rounded-lg text-sm font-medium",
                    "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700",
                    "transition-colors",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
