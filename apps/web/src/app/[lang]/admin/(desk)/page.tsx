import { redirect } from "next/navigation";

// Queues first (blueprint I.4).
export default async function AdminHome({ params }: PageProps<"/[lang]/admin">) {
  const { lang } = await params;
  redirect(`/${lang}/admin/problems`);
}
